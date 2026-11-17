import json
import math
from collections.abc import AsyncIterator

import aiohttp
import pytest

from custom_components.thermia_cloud.client.api import ThermiaApi
from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import ThermiaConfig
from custom_components.thermia_cloud.client.errors import RateLimitError, RegisterWriteError
from custom_components.thermia_cloud.client.http import ThermiaHttp
from custom_components.thermia_cloud.client.models import RegisterSpec
from custom_components.thermia_cloud.client.validation import validate_write

from .conftest import AUTH_PATH, FIXTURES, FakeCloud, Reply

TOKEN = f"{AUTH_PATH}/oauth2/v2.0/token"
WRITE = "/api/v1/Registers/Installations/5/Registers"


def spec(name: str, group: str) -> RegisterSpec:
    raw = json.loads((FIXTURES / f"group_{group}.json").read_text())
    return RegisterSpec.from_json(next(r for r in raw if r["registerName"] == name))


CURVE = spec("REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE")  # 22..56 step 1
HOT_WATER_MODE = spec("REG_OPERATIONMODE", "REG_GROUP_HOT_WATER")  # max=1 but visible 0,1,2
OPERATION_MODE = spec("REG_OPERATIONMODE", "REG_GROUP_OPERATIONAL_OPERATION")  # no min/max
READ_ONLY = spec("REG_OPER_DATA_SUPPLY_MA_SA", "REG_GROUP_TEMPERATURES")
FLAGS = spec("COMP_STATUS_ITEC", "REG_GROUP_OPERATIONAL_STATUS")


@pytest.mark.parametrize(
    ("register", "value", "sent"),
    [
        (CURVE, 22, 22),
        (CURVE, 56.0, 56),
        (CURVE, 30, 30),
        (HOT_WATER_MODE, 2, 2),  # visible wins over max=1
        (HOT_WATER_MODE, 0, 0),
        (OPERATION_MODE, 4, 4),
    ],
)
def test_valid_writes(register: RegisterSpec, value: float, sent: float) -> None:
    result = validate_write(register, value)
    assert result == sent and isinstance(result, int)


@pytest.mark.parametrize(
    ("register", "value"),
    [
        (CURVE, 21),  # below min: rejected, never clamped
        (CURVE, 57),
        (CURVE, 30.5),  # not a multiple of the step
        (CURVE, math.nan),
        (CURVE, math.inf),
        (CURVE, True),
        (CURVE, "30"),
        (HOT_WATER_MODE, 3),  # not a visible value
        (OPERATION_MODE, 5),
        (OPERATION_MODE, -1),
        (READ_ONLY, 30),  # read-only register
        (FLAGS, 1),  # status flags cannot be written
    ],
)
def test_invalid_writes_are_rejected(register: RegisterSpec, value: object) -> None:
    with pytest.raises(RegisterWriteError):
        validate_write(register, value)  # type: ignore[arg-type]


def test_hidden_enum_values_are_not_writable() -> None:
    # value 0 exists as a hidden REG_VALUE_STATUS_OFF *and* a visible Comfort: allowed via Comfort,
    # but a value that is only hidden must be refused
    circuit = spec("REG_ACTIVATE_CIRC1", "REG_GROUP_HEATING_CURVE_CIRC1")
    assert validate_write(circuit, 1) == 1
    with pytest.raises(RegisterWriteError):
        validate_write(circuit, 0)  # OFF is hidden for this register


@pytest.fixture
async def api(config: ThermiaConfig, cloud: FakeCloud) -> AsyncIterator[ThermiaApi]:
    cloud.on("POST", TOKEN, cloud.token())
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    async with aiohttp.ClientSession() as session:
        yield ThermiaApi(ThermiaHttp(session, auth, config.api_base_url, sleep=_no_sleep))
    await auth.close()


async def _no_sleep(_: float) -> None:
    return None


async def test_write_posts_the_documented_body(api: ThermiaApi, cloud: FakeCloud) -> None:
    cloud.on("POST", WRITE, Reply(200, ""))  # an empty 200 body is fine
    assert await api.write_register(5, CURVE, 30) == 30
    [(_, _, body)] = [b for b in cloud.bodies if b[1] == WRITE]
    assert body["registerSpecificationId"] == CURVE.register_id
    assert body["registerValue"] == 30 and body["clientUuid"]


async def test_invalid_value_never_reaches_the_cloud(api: ThermiaApi, cloud: FakeCloud) -> None:
    with pytest.raises(RegisterWriteError):
        await api.write_register(5, CURVE, 99)
    assert cloud.count("POST", WRITE) == 0


async def test_rejected_write_raises_write_error(api: ThermiaApi, cloud: FakeCloud) -> None:
    cloud.always("POST", WRITE, Reply(400, {"error": "no"}))
    with pytest.raises(RegisterWriteError):
        await api.write_register(5, CURVE, 30)


async def test_the_clouds_answer_is_part_of_the_error(api: ThermiaApi, cloud: FakeCloud) -> None:
    cloud.always("POST", WRITE, Reply(400, "register is not writable right now"))
    with pytest.raises(RegisterWriteError, match="not writable right now"):
        await api.write_register(5, CURVE, 30)


async def test_rate_limit_is_passed_through(api: ThermiaApi, cloud: FakeCloud) -> None:
    cloud.always("POST", WRITE, Reply(429, "", {"Retry-After": "7"}))
    with pytest.raises(RateLimitError):
        await api.write_register(5, CURVE, 30)


async def test_writes_to_one_installation_are_serialized(api: ThermiaApi, cloud: FakeCloud) -> None:
    import asyncio

    active = 0
    peak = 0
    original = api._http.request

    async def slow(*args: object, **kwargs: object) -> object:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    api._http.request = slow  # type: ignore[method-assign]
    cloud.always("POST", WRITE, Reply(200, ""))
    await asyncio.gather(*(api.write_register(5, CURVE, 22 + i) for i in range(4)))
    assert peak == 1 and cloud.count("POST", WRITE) == 4


async def test_the_write_body_uses_the_write_id_never_the_index(
    api: ThermiaApi, cloud: FakeCloud
) -> None:
    cloud.on("POST", WRITE, Reply(200, ""))
    await api.write_register(5, CURVE, 30)
    [(_, _, body)] = [b for b in cloud.bodies if b[1] == WRITE]
    assert set(body) == {"registerSpecificationId", "registerValue", "clientUuid"}
    assert body["registerSpecificationId"] == CURVE.register_id != CURVE.register_index
