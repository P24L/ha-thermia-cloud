import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.catalog.schema import Risk
from custom_components.thermia_cloud.client.errors import RegisterWriteError
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_READ_ONLY,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import FIXTURES, INSTALLATION_ID, FakeApi, FakeAuth


def spec_of(name: str, group: str) -> dict:
    raw = json.loads((FIXTURES / f"group_{group}.json").read_text())
    return next(r for r in raw if r["registerName"] == name)


CURVE = spec_of("REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE")
OPMODE = spec_of("REG_OPERATIONMODE", "REG_GROUP_OPERATIONAL_OPERATION")
HW_MODE = spec_of("REG_OPERATIONMODE", "REG_GROUP_HOT_WATER")
HW_STATUS = spec_of("REG_HOT_WATER_STATUS", "REG_GROUP_HOT_WATER")


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture(autouse=True)
def fake_client(api: FakeApi):  # type: ignore[no-untyped-def]
    """Stays patched for the whole test, so reloads of the entry use the fake as well."""
    with patch(
        "custom_components.thermia_cloud.async_build_client",
        side_effect=lambda *_: (None, FakeAuth(), api),
    ):
        yield


async def setup_entry(
    hass: HomeAssistant, api: FakeApi, *, read_only: bool = False
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={
            CONF_INSTALLATIONS: [INSTALLATION_ID],
            CONF_SCAN_INTERVAL: 60,
            CONF_READ_ONLY: read_only,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def eid(hass: HomeAssistant, platform: str, spec: dict, suffix: str = "") -> str:
    found = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{INSTALLATION_ID}_{spec['registerIndex']}{suffix}"
    )
    assert found, (platform, spec["registerName"])
    return found


async def tick(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_number_write_then_readback(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup_entry(hass, api)
    number = eid(hass, "number", CURVE)
    state = hass.states.get(number)
    assert state.state == "22.0" and state.attributes["min"] == 22 and state.attributes["max"] == 56
    assert state.attributes["risk"] == "heating"

    api.apply_writes = False  # accepted, but not visible yet
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert api.writes == [(CURVE["registerId"], 30)]
    state = hass.states.get(number)
    assert state.state == "22.0" and state.attributes["pending_value"] == 30  # real value + pending
    coordinator = entry.runtime_data.installations[0].coordinator
    assert coordinator.update_interval == timedelta(seconds=5)  # fast poll

    api.apply_queued()
    await tick(hass, 6)
    state = hass.states.get(number)
    assert state.state == "30.0" and "pending_value" not in state.attributes
    assert coordinator.update_interval == timedelta(seconds=60)  # back to normal


async def test_select_writes_visible_values(hass: HomeAssistant, api: FakeApi) -> None:
    await setup_entry(hass, api)
    operation = eid(hass, "select", OPMODE)
    assert hass.states.get(operation).attributes["options"] == [
        "off",
        "auto",
        "compressor",
        "auxiliary",
        "hot_water",
    ]
    assert hass.states.get(operation).state == "auto"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": operation, "option": "compressor"}, blocking=True
    )
    assert api.writes[-1] == (OPMODE["registerId"], 2)

    hot_water_mode = eid(hass, "select", HW_MODE)
    # "Away" is value 2 although the cloud says max=1: the visible values win
    assert hass.states.get(hot_water_mode).attributes["options"] == ["comfort", "economy", "away"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": hot_water_mode, "option": "away"}, blocking=True
    )
    assert api.writes[-1] == (HW_MODE["registerId"], 2)


async def test_switch_turns_hot_water_on_and_off(hass: HomeAssistant, api: FakeApi) -> None:
    await setup_entry(hass, api)
    switch = eid(hass, "switch", HW_STATUS)
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert api.writes[-1] == (HW_STATUS["registerId"], 0)
    await hass.async_block_till_done()
    assert hass.states.get(switch).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert api.writes[-1] == (HW_STATUS["registerId"], 1)


@pytest.mark.parametrize(
    ("platform", "service", "data", "spec"),
    [
        ("number", "set_value", {"value": 30}, CURVE),
        ("select", "select_option", {"option": "compressor"}, OPMODE),
        ("switch", "turn_off", {}, HW_STATUS),
    ],
)
async def test_read_only_mode_blocks_every_write(
    hass: HomeAssistant, api: FakeApi, platform: str, service: str, data: dict, spec: dict
) -> None:
    await setup_entry(hass, api, read_only=True)
    with pytest.raises(HomeAssistantError, match="Read-only mode is on"):
        await hass.services.async_call(
            platform, service, {"entity_id": eid(hass, platform, spec), **data}, blocking=True
        )
    assert api.writes == []
    assert "write_register" not in api.calls  # not even attempted


async def test_cloud_rejection_is_raised_to_the_caller(hass: HomeAssistant, api: FakeApi) -> None:
    await setup_entry(hass, api)
    api.write_error = RegisterWriteError("the cloud answered HTTP 400")
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": eid(hass, "switch", HW_STATUS)}, blocking=True
        )
    assert api.writes == []


def device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return (
        dr.async_get(hass)
        .async_get_device_by_identifier((DOMAIN, str(INSTALLATION_ID)), entry.entry_id)
        .id
    )


async def call_service(hass: HomeAssistant, entry: MockConfigEntry, **data: object) -> None:
    await hass.services.async_call(
        DOMAIN, "set_register", {"device_id": device_id(hass, entry), **data}, blocking=True
    )


async def test_service_writes_by_name_and_by_index(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup_entry(hass, api)
    await call_service(
        hass, entry, group="REG_GROUP_HEATING_CURVE", register="REG_HEATING_HEAT_CURVE", value=31
    )
    await call_service(
        hass, entry, group="REG_GROUP_HEATING_CURVE", register=CURVE["registerIndex"], value=32
    )
    assert api.writes == [(CURVE["registerId"], 31), (CURVE["registerId"], 32)]


async def test_service_validates_and_refuses(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup_entry(hass, api)
    with pytest.raises(HomeAssistantError, match="Value rejected"):
        await call_service(
            hass,
            entry,
            group="REG_GROUP_HEATING_CURVE",
            register="REG_HEATING_HEAT_CURVE",
            value=99,
        )
    with pytest.raises(HomeAssistantError, match="No such register"):
        await call_service(hass, entry, group="REG_GROUP_HEATING_CURVE", register="NOPE", value=1)
    with pytest.raises(HomeAssistantError, match=r"cannot be changed|Value rejected"):
        await call_service(
            hass,
            entry,
            group="REG_GROUP_TEMPERATURES",
            register="REG_OPER_DATA_SUPPLY_MA_SA",
            value=1,
        )  # read-only register
    assert api.writes == []


async def test_service_refuses_installer_level_registers(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup_entry(hass, api)
    with (
        patch("custom_components.thermia_cloud.writer.effective_risk", return_value=Risk.SERVICE),
        pytest.raises(HomeAssistantError, match="installer-level"),
    ):
        await call_service(
            hass,
            entry,
            group="REG_GROUP_HEATING_CURVE",
            register="REG_HEATING_HEAT_CURVE",
            value=31,
        )
    assert api.writes == []


async def test_service_obeys_read_only_mode(hass: HomeAssistant, api: FakeApi) -> None:
    entry = await setup_entry(hass, api, read_only=True)
    with pytest.raises(HomeAssistantError, match="Read-only mode"):
        await call_service(
            hass,
            entry,
            group="REG_GROUP_HEATING_CURVE",
            register="REG_HEATING_HEAT_CURVE",
            value=31,
        )
    assert api.writes == []


async def test_service_with_unknown_device_fails(hass: HomeAssistant, api: FakeApi) -> None:
    await setup_entry(hass, api)
    with pytest.raises(HomeAssistantError, match="Unknown installation"):
        await hass.services.async_call(
            DOMAIN,
            "set_register",
            {"device_id": "nope", "group": "G", "register": "R", "value": 1},
            blocking=True,
        )


async def test_unseen_write_is_given_up_after_30_seconds(
    hass: HomeAssistant, api: FakeApi, caplog: pytest.LogCaptureFixture, freezer
) -> None:
    entry = await setup_entry(hass, api)
    api.apply_writes = False
    await hass.services.async_call(
        "number", "set_value", {"entity_id": eid(hass, "number", CURVE), "value": 30}, blocking=True
    )
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.installations[0].coordinator
    assert coordinator.pending
    caplog.clear()
    for _ in range(8):  # 40 s of fast polling, the value never shows up
        freezer.tick(timedelta(seconds=5))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert not coordinator.pending
    assert coordinator.update_interval == timedelta(seconds=60)
    assert sum("not seen in the cloud yet" in r.message for r in caplog.records) == 1


async def test_options_flow_switches_read_only_on_and_reloads(
    hass: HomeAssistant, api: FakeApi
) -> None:
    entry = await setup_entry(hass, api)
    number = eid(hass, "number", CURVE)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 30}, blocking=True
    )
    assert len(api.writes) == 1

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 30, "read_only": True, "timeout": 20, "debug_attributes": True},
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_READ_ONLY] is True and entry.options[CONF_INSTALLATIONS]
    assert entry.runtime_data.installations[0].coordinator.update_interval == timedelta(seconds=30)
    assert hass.states.get(number).attributes["register_name"] == "REG_HEATING_HEAT_CURVE"

    with pytest.raises(HomeAssistantError, match="Read-only mode"):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 31}, blocking=True
        )
    assert len(api.writes) == 1
