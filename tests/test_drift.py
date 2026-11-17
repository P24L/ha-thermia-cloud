"""The cloud's register set changes (e.g. a circuit switched between Curve and Constant)."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import FIXTURES, INSTALLATION_ID, FakeApi, FakeAuth

OUTDOOR = next(
    r
    for r in json.loads((FIXTURES / "group_REG_GROUP_TEMPERATURES.json").read_text())
    if r["registerName"] == "REG_OPER_DATA_OUTDOOR_TEMP_MA_SA"
)
NEW_ID = 9990100


def new_register() -> dict:
    """A writable slider that only exists in some mode (like a constant-temperature setpoint)."""
    return {
        **OUTDOOR,
        "registerId": NEW_ID,
        "registerIndex": NEW_ID,
        "registerName": "REG_X_MODE_ONLY_SETPOINT",
        "presentation": "Slider",
        "isReadOnly": False,
        "minValue": 5.0,
        "maxValue": 60.0,
        "step": 1.0,
        "modifier": 0,
        "registerValue": 35.0,
    }


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


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={CONF_INSTALLATIONS: [INSTALLATION_ID], CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def poll(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def entity_for(hass: HomeAssistant, platform: str, register_id: int) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{INSTALLATION_ID}_{register_id}"
    )


async def test_new_register_is_picked_up_by_an_automatic_rediscovery(
    hass: HomeAssistant, api: FakeApi
) -> None:
    await setup(hass)
    assert entity_for(hass, "number", NEW_ID) is None
    before = api.calls.count("get_history_registers")

    api.extra = [new_register()]  # the cloud starts returning a register we have never seen
    await poll(hass, 61)

    assert api.calls.count("get_history_registers") == before + 1  # rediscovered once
    new_entity = entity_for(hass, "number", NEW_ID)
    assert new_entity  # generic writable slider -> number (disabled by default)
    assert (
        er.async_get(hass).async_get(new_entity).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_rediscovery_is_rate_limited_across_reloads(
    hass: HomeAssistant, api: FakeApi
) -> None:
    await setup(hass)
    api.extra = [new_register()]
    await poll(hass, 61)
    count = api.calls.count("get_history_registers")

    api.extra = [
        new_register(),
        {**new_register(), "registerId": NEW_ID + 1, "registerIndex": NEW_ID + 1},
    ]
    await poll(hass, 130)  # another change, ~1 minute later: must not rediscover again
    assert api.calls.count("get_history_registers") == count


async def test_vanished_registers_trigger_rediscovery_after_three_polls(
    hass: HomeAssistant, api: FakeApi
) -> None:
    entry = await setup(hass)
    before = api.calls.count("get_history_registers")
    api.hide.add("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA")

    await poll(hass, 61)
    await poll(hass, 125)
    assert api.calls.count("get_history_registers") == before  # two polls are not enough
    await poll(hass, 190)
    assert api.calls.count("get_history_registers") == before + 1

    # after rediscovery the register is no longer expected: nothing is "missing" any more
    coordinator = entry.runtime_data.installations[0].coordinator
    assert coordinator.missing_since == {}
    assert not any(
        i.domain == DOMAIN and "vanished" in i.issue_id for i in ir.async_get(hass).issues.values()
    )


async def test_one_odd_answer_does_not_rediscover(hass: HomeAssistant, api: FakeApi) -> None:
    await setup(hass)
    before = api.calls.count("get_history_registers")
    api.hide.add("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA")
    await poll(hass, 61)
    api.hide.clear()
    await poll(hass, 125)
    await poll(hass, 190)
    assert api.calls.count("get_history_registers") == before
