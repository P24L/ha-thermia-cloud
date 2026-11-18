"""The water heater entity built from the hot water switch, mode and temperature."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

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

HOT_WATER = json.loads((FIXTURES / "group_REG_GROUP_HOT_WATER.json").read_text())
STATUS_ID = next(r["registerId"] for r in HOT_WATER if r["registerName"] == "REG_HOT_WATER_STATUS")
MODE_ID = next(r["registerId"] for r in HOT_WATER if r["registerName"] == "REG_OPERATIONMODE")


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture(autouse=True)
def fake_client(api: FakeApi):  # type: ignore[no-untyped-def]
    with patch(
        "custom_components.thermia_cloud.async_build_client",
        side_effect=lambda *_: (None, FakeAuth(), api),
    ):
        yield


async def setup(hass: HomeAssistant, read_only: bool = False) -> MockConfigEntry:
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


def heater(hass: HomeAssistant):  # type: ignore[no-untyped-def]
    eid = er.async_get(hass).async_get_entity_id(
        "water_heater", DOMAIN, f"{INSTALLATION_ID}_water_heater"
    )
    assert eid
    return eid, hass.states.get(eid)


async def test_the_water_heater_shows_the_mode_and_the_temperature(hass: HomeAssistant) -> None:
    await setup(hass)
    _, state = heater(hass)
    assert state.state == "comfort"  # switch on, mode value 0
    assert state.attributes["current_temperature"] == 51.0
    assert state.attributes["operation_list"] == ["off", "comfort", "economy", "away"]


async def test_modes_and_on_off_write_the_registers(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass)
    eid, _ = heater(hass)
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {"entity_id": eid, "operation_mode": "economy"},
        blocking=True,
    )
    assert api.writes[-1] == (MODE_ID, 1)
    await hass.services.async_call("water_heater", "turn_off", {"entity_id": eid}, blocking=True)
    assert api.writes[-1] == (STATUS_ID, 0)
    await hass.async_block_till_done()
    assert heater(hass)[1].state == "off"
    await hass.services.async_call("water_heater", "turn_on", {"entity_id": eid}, blocking=True)
    assert api.writes[-1] == (STATUS_ID, 1)


async def test_choosing_a_mode_while_off_switches_on_and_waits_for_the_mode_register(
    hass: HomeAssistant, api: FakeApi
) -> None:
    await setup(hass)
    eid, _ = heater(hass)
    api.values[STATUS_ID] = 0.0  # hot water is off: the mode register is gone
    api.hide_ids = {MODE_ID}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert heater(hass)[1].state == "off"

    async def mode_register_appears(_: float) -> None:
        api.hide_ids.clear()

    with patch("custom_components.thermia_cloud.water_heater.asyncio.sleep", mode_register_appears):
        await hass.services.async_call(
            "water_heater",
            "set_operation_mode",
            {"entity_id": eid, "operation_mode": "economy"},
            blocking=True,
        )
    assert api.writes[-2:] == [(STATUS_ID, 1), (MODE_ID, 1)]


async def test_read_only_mode_blocks_the_water_heater(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass, read_only=True)
    eid, _ = heater(hass)
    with pytest.raises(HomeAssistantError, match="Read-only mode"):
        await hass.services.async_call(
            "water_heater", "turn_off", {"entity_id": eid}, blocking=True
        )
    assert api.writes == []
