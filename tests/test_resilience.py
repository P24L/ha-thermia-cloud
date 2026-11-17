"""Counters, independent installations, renames and authentication failures at runtime."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.client.errors import AuthError
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import FIXTURES, FakeApi, FakeAuth


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


async def setup(hass: HomeAssistant, installations: list[int]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={CONF_INSTALLATIONS: installations, CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def poll(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def index_of(name: str, group: str) -> int:
    raw = json.loads((FIXTURES / f"group_{group}.json").read_text())
    return next(r["registerIndex"] for r in raw if r["registerName"] == name)


def sensor(hass: HomeAssistant, installation: int, name: str, group: str):  # type: ignore[no-untyped-def]
    eid = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{installation}_{index_of(name, group)}"
    )
    return hass.states.get(eid)


async def test_a_counter_that_dips_slightly_is_not_reported_as_a_reset(
    hass: HomeAssistant, api: FakeApi
) -> None:
    await setup(hass, [42])
    hours = ("REG_OPER_TIME_COMPRESSOR", "REG_GROUP_OPERATIONAL_TIME")
    assert sensor(hass, 42, *hours).state == "9822.0"
    api.overrides["REG_OPER_TIME_COMPRESSOR"] = 9821.0  # a rounding dip
    await poll(hass, 61)
    assert sensor(hass, 42, *hours).state == "9822.0"  # held
    api.overrides["REG_OPER_TIME_COMPRESSOR"] = 9900.0  # normal growth
    await poll(hass, 125)
    assert sensor(hass, 42, *hours).state == "9900.0"
    api.overrides["REG_OPER_TIME_COMPRESSOR"] = 100.0  # a real reset (replaced counter)
    await poll(hass, 190)
    assert sensor(hass, 42, *hours).state == "100.0"


async def test_one_failing_installation_does_not_stop_the_others(
    hass: HomeAssistant, api: FakeApi
) -> None:
    api.installation_ids = [42, 43]
    await setup(hass, [42, 43])
    outdoor = ("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES")
    assert sensor(hass, 43, *outdoor).state == "4.0"

    api.fail_installations = {43}  # its gateway/API starts failing
    api.overrides["REG_OPER_DATA_OUTDOOR_TEMP_MA_SA"] = 7.0
    await poll(hass, 61)
    assert sensor(hass, 42, *outdoor).state == "7.0"  # still updating
    assert sensor(hass, 43, *outdoor).state == "unavailable"

    api.fail_installations = set()
    await poll(hass, 125)
    assert sensor(hass, 43, *outdoor).state == "7.0"  # and it recovers by itself


async def test_renaming_an_installation_keeps_every_entity(
    hass: HomeAssistant, api: FakeApi
) -> None:
    entry = await setup(hass, [42])
    registry = er.async_get(hass)
    before = {e.unique_id: e.entity_id for e in registry.entities.values() if e.platform == DOMAIN}
    assert before

    api.installation_name = "Renamed in the Thermia app"
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = {e.unique_id: e.entity_id for e in registry.entities.values() if e.platform == DOMAIN}
    assert after == before  # same unique ids, same entity ids


async def test_a_failed_authentication_asks_for_reauth_once_without_a_retry_storm(
    hass: HomeAssistant, api: FakeApi
) -> None:
    entry = await setup(hass, [42])
    api.error = AuthError("password changed")
    reads = len(api.calls)
    for seconds in (61, 125, 190, 255):
        await poll(hass, seconds)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]  # one flow, not four
    assert len(api.calls) - reads <= 2  # not hammering the cloud with a rejected password
    assert entry.state.value in ("loaded", "setup_error")
