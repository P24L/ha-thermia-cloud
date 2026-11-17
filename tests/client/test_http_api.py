from collections.abc import AsyncIterator

import aiohttp
import pytest

from custom_components.thermia_cloud.client.api import ThermiaApi
from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import ThermiaConfig
from custom_components.thermia_cloud.client.errors import ApiError, NetworkError, RateLimitError
from custom_components.thermia_cloud.client.http import ThermiaHttp

from .conftest import AUTH_PATH, FakeCloud, Reply, load_api, load_group

TOKEN = f"{AUTH_PATH}/oauth2/v2.0/token"
X = "/api/v1/x"


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def http(config: ThermiaConfig, cloud: FakeCloud) -> AsyncIterator[ThermiaHttp]:
    cloud.on("POST", TOKEN, cloud.token(access="a1", refresh="r1"))
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    async with aiohttp.ClientSession() as session:
        yield ThermiaHttp(session, auth, config.api_base_url, sleep=_no_sleep)
    await auth.close()


async def test_401_reauthenticates_once_and_retries(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.on("GET", X, Reply(401), Reply(body={"ok": True}))
    cloud.on("POST", TOKEN, cloud.token(access="a2", refresh="r2"))
    assert await http.request("GET", X) == {"ok": True}
    assert cloud.count("POST", TOKEN) == 2


async def test_second_401_is_an_api_error(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.always("GET", X, Reply(401))
    cloud.on("POST", TOKEN, cloud.token(access="a2", refresh="r2"))
    with pytest.raises(ApiError) as err:
        await http.request("GET", X)
    assert err.value.status == 401
    assert cloud.count("GET", X) == 2


async def test_429_raises_with_retry_after(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.always("GET", X, Reply(429, "", {"Retry-After": "30"}))
    with pytest.raises(RateLimitError) as err:
        await http.request("GET", X)
    assert err.value.retry_after == 30


async def test_5xx_is_retried_a_bounded_number_of_times(
    http: ThermiaHttp, cloud: FakeCloud
) -> None:
    cloud.always("GET", X, Reply(503))
    with pytest.raises(ApiError) as err:
        await http.request("GET", X)
    assert err.value.status == 503
    assert cloud.count("GET", X) == 3


async def test_5xx_then_success(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.on("GET", X, Reply(502), Reply(body=[1]))
    assert await http.request("GET", X) == [1]


async def test_connection_error_is_network_error(config: ThermiaConfig, cloud: FakeCloud) -> None:
    cloud.on("POST", TOKEN, cloud.token())
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    async with aiohttp.ClientSession() as session:
        dead = ThermiaHttp(session, auth, "http://127.0.0.1:9", sleep=_no_sleep)
        with pytest.raises(NetworkError):
            await dead.request("GET", X)
    await auth.close()


async def test_group_registers_from_fixture_and_empty_group(
    http: ThermiaHttp, cloud: FakeCloud
) -> None:
    api = ThermiaApi(http)
    base = "/api/v1/Registers/Installations/1/Groups"
    cloud.on("GET", f"{base}/REG_GROUP_HOT_WATER", Reply(body=load_group("REG_GROUP_HOT_WATER")))
    cloud.on("GET", f"{base}/REG_GROUP_POOL", Reply(body=[]))
    hot_water = await api.get_group_registers(1, "REG_GROUP_HOT_WATER")
    assert {spec.name for spec, _ in hot_water} >= {"REG_HOT_WATER_STATUS", "REG_OPERATIONMODE"}
    assert await api.get_group_registers(1, "REG_GROUP_POOL") == []


async def test_installations_listing(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.on("GET", "/api/v1/installationsInfo", Reply(body=load_api("installations_info")))
    [inst] = await ThermiaApi(http).list_installations()
    assert inst.model == "iTec" and inst.is_online


async def test_installation_detail(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.on("GET", "/api/v1/installations/0", Reply(body=load_api("installation")))
    assert (await ThermiaApi(http).get_installation(0)).profile_id == 1005


async def test_status_is_passed_through(http: ThermiaHttp, cloud: FakeCloud) -> None:
    cloud.on("GET", "/api/v1/installationstatus/0/status", Reply(body=load_api("status")))
    assert (await ThermiaApi(http).get_status(0))["outdoorTemperature"] == 4.0
