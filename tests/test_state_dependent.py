"""Registers that the cloud only returns in some state (circuit mode, hot water on/off)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.client.models import RegisterSpec
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.thermia_cloud.discovery import (
    Discovery,
    RememberedSpec,
    merge_remembered,
)

from .fakes import FIXTURES, INSTALLATION_ID, FakeApi, FakeAuth

CIRC1 = json.loads((FIXTURES / "group_REG_GROUP_HEATING_CURVE_CIRC1.json").read_text())
CURVE1 = next(r for r in CIRC1 if r["registerName"] == "REG_HEATING_HEAT_CURVE")
CONSTANT_INDEX = 1028  # REG_HEATING_HEAT_CURVE1_CONSTANT


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


def state(hass: HomeAssistant, index: int):  # type: ignore[no-untyped-def]
    eid = er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{INSTALLATION_ID}_{index}")
    return hass.states.get(eid) if eid else None


async def poll(hass: HomeAssistant, freezer, seconds: int = 61) -> None:  # type: ignore[no-untyped-def]
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_circuit_mode_round_trip_keeps_both_sets_of_entities(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    entry = await setup(hass)
    curve = CURVE1["registerIndex"]
    assert state(hass, curve).state == "22.0" and state(hass, CONSTANT_INDEX) is None
    discoveries = api.calls.count("get_history_registers")

    api.constant_mode = True  # the circuit is switched to Constant
    await poll(hass, freezer)
    assert api.calls.count("get_history_registers") == discoveries + 1  # one rediscovery
    assert state(hass, CONSTANT_INDEX).state == "41.0"  # enabled by the catalog
    assert state(hass, curve).state == "unavailable"  # remembered, not dropped

    api.constant_mode = False  # ... and back to Curve: no new rediscovery needed
    await poll(hass, freezer)
    await poll(hass, freezer)
    assert api.calls.count("get_history_registers") == discoveries + 1
    assert state(hass, curve).state == "22.0"
    assert state(hass, CONSTANT_INDEX).state == "unavailable"

    # a week later the absent registers are still no reason for a Repair issue
    freezer.tick(timedelta(days=8))
    await poll(hass, freezer)
    assert not [i for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN]
    assert entry.runtime_data.installations[0].coordinator.missing_since == {}


# -- remembering ---------------------------------------------------------------------------------


def spec(register_id: int, name: str = "R") -> RegisterSpec:
    raw = {**CURVE1, "registerId": register_id, "registerIndex": register_id, "registerName": name}
    return RegisterSpec.from_json(raw)


def discovery(*specs: RegisterSpec, fetched: datetime, remembered=()) -> Discovery:  # type: ignore[no-untyped-def]
    return Discovery(1, 1, ("G",), tuple(specs), (), fetched, tuple(remembered))


NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_vanished_specs_are_remembered() -> None:
    previous = discovery(spec(1, "A"), spec(2, "B"), fetched=NOW - timedelta(days=1))
    fresh = discovery(spec(2, "B"), spec(3, "C"), fetched=NOW)
    merged = merge_remembered(previous, fresh, now=NOW)
    assert [r.spec.name for r in merged.remembered] == ["A"]
    assert [s.name for s in merged.all_specs] == ["B", "C", "A"]
    assert merged.remembered[0].last_seen == NOW - timedelta(days=1)


def test_a_returning_register_is_no_longer_remembered() -> None:
    old = RememberedSpec(spec(1, "A"), NOW - timedelta(days=2))
    previous = discovery(spec(2, "B"), fetched=NOW - timedelta(days=1), remembered=[old])
    merged = merge_remembered(previous, discovery(spec(1, "A"), spec(2, "B"), fetched=NOW), now=NOW)
    assert merged.remembered == ()


def test_remembered_specs_expire_after_30_days_or_are_forgotten_on_request() -> None:
    old = RememberedSpec(spec(1, "A"), NOW - timedelta(days=31))
    recent = RememberedSpec(spec(2, "B"), NOW - timedelta(days=29))
    previous = discovery(spec(9, "Z"), fetched=NOW - timedelta(days=1), remembered=[old, recent])
    fresh = discovery(spec(9, "Z"), fetched=NOW)
    assert [r.spec.name for r in merge_remembered(previous, fresh, now=NOW).remembered] == ["B"]
    assert merge_remembered(previous, fresh, forget=True, now=NOW).remembered == ()
    assert merge_remembered(None, fresh, now=NOW).remembered == ()


def test_remembered_specs_survive_the_cache_round_trip() -> None:
    kept = RememberedSpec(spec(1, "A"), NOW)
    original = discovery(spec(2, "B"), fetched=NOW, remembered=[kept])
    restored = Discovery.from_json(json.loads(json.dumps(original.to_json())))
    assert restored == original
    legacy = original.to_json()
    del legacy["remembered"]  # a cache written before this feature
    assert Discovery.from_json(legacy).remembered == ()
