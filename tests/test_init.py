import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.client.errors import AuthError, NetworkError
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import FIXTURES, INSTALLATION_ID, FakeApi, FakeAuth


def index_of(name: str, group: str) -> int:
    raw = json.loads((FIXTURES / f"group_{group}.json").read_text())
    return next(r["registerIndex"] for r in raw if r["registerName"] == name)


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={CONF_INSTALLATIONS: [INSTALLATION_ID], CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi) -> FakeAuth:
    auth = FakeAuth()
    with patch(
        "custom_components.thermia_cloud.async_build_client", return_value=(None, auth, api)
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return auth


def entity_id(hass: HomeAssistant, platform: str, unique_suffix: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{INSTALLATION_ID}_{unique_suffix}"
    )


async def test_setup_creates_entities_from_the_fixture(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED

    outdoor = entity_id(
        hass, "sensor", str(index_of("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES"))
    )
    assert outdoor and hass.states.get(outdoor).state == "4.0"
    assert hass.states.get(outdoor).attributes["unit_of_measurement"] == "°C"
    assert "register_timestamp" in hass.states.get(outdoor).attributes

    status = index_of("COMP_STATUS_ITEC", "REG_GROUP_OPERATIONAL_STATUS")
    compressor = entity_id(hass, "binary_sensor", f"{status}_1")
    defrost = entity_id(hass, "binary_sensor", f"{status}_32")
    assert hass.states.get(compressor).state == "on"  # status 19 = compressor + heating
    assert hass.states.get(defrost).state == "off"

    # catalog says disabled by default: registered but without a state
    stop = entity_id(hass, "sensor", "0")  # nothing at all with this key
    assert stop is None


async def test_disabled_by_default_entities_exist_in_the_registry_only(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    imm1 = entity_id(
        hass, "sensor", str(index_of("REG_OPER_TIME_IMM1", "REG_GROUP_OPERATIONAL_TIME"))
    )
    assert imm1 is not None
    assert er.async_get(hass).async_get(imm1).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(imm1) is None


async def test_devices_main_and_child(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    registry = dr.async_get(hass)
    main = registry.async_get_device_by_identifier((DOMAIN, str(INSTALLATION_ID)), entry.entry_id)
    child = registry.async_get_device_by_identifier(
        (DOMAIN, f"{INSTALLATION_ID}_circuit_1"), entry.entry_id
    )
    assert main and main.manufacturer == "Thermia" and main.model == "iTec"
    assert child and child.via_device_id == main.id


async def test_distribution_sensor_lives_on_the_circuit_device(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    eid = entity_id(
        hass, "sensor", str(index_of("REG_OPER_DATA_DISTR_CIR1", "REG_GROUP_TEMPERATURES"))
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{INSTALLATION_ID}_circuit_1"), entry.entry_id
    )
    assert er.async_get(hass).async_get(eid).device_id == device.id


async def test_value_based_condition_makes_entity_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    api.overrides["REG_HOT_WATER_TEMPERATURE"] = -100  # "sensor not connected"
    await setup(hass, entry, api)
    eid = entity_id(
        hass, "sensor", str(index_of("REG_HOT_WATER_TEMPERATURE", "REG_GROUP_TEMPERATURES"))
    )
    assert hass.states.get(eid).state == "unavailable"


async def test_poll_failure_and_recovery(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    eid = entity_id(
        hass, "sensor", str(index_of("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES"))
    )
    api.error = NetworkError("down")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "unavailable"
    api.error = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=125))
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "4.0"


async def test_vanished_register_becomes_unavailable(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    await setup(hass, entry, api)
    eid = entity_id(hass, "switch", "x")  # no switches yet (P5.3)
    assert eid is None
    outdoor = entity_id(
        hass, "sensor", str(index_of("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES"))
    )
    api.hide.add("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(outdoor).state == "unavailable"


async def test_auth_error_does_not_load_the_entry(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    api.error = AuthError("bad")
    auth = await setup(hass, entry, api)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert auth.closed


async def test_network_error_retries_setup(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    api.error = NetworkError("down")
    auth = await setup(hass, entry, api)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert auth.closed


async def test_unload_closes_the_client(
    hass: HomeAssistant, entry: MockConfigEntry, api: FakeApi
) -> None:
    auth = await setup(hass, entry, api)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert auth.closed
