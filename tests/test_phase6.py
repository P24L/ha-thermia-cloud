"""Options, names/language, buttons and Repair issues."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.client.errors import PolicyAcceptanceError
from custom_components.thermia_cloud.const import (
    CONF_EXPOSE_UNKNOWN,
    CONF_INSTALLATIONS,
    CONF_LABEL_LANGUAGE,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import FIXTURES, INSTALLATION_ID, FakeApi, FakeAuth


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


def make_entry(hass: HomeAssistant, **options: object) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={CONF_INSTALLATIONS: [INSTALLATION_ID], CONF_SCAN_INTERVAL: 60, **options},
    )
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def register(name: str, group: str) -> dict:
    raw = json.loads((FIXTURES / f"group_{group}.json").read_text())
    return next(r for r in raw if r["registerName"] == name)


OUTDOOR = register("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES")


def name_of(hass: HomeAssistant, platform: str, index: int, suffix: str = "") -> str:
    eid = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{INSTALLATION_ID}_{index}{suffix}"
    )
    assert eid
    return hass.states.get(eid).attributes["friendly_name"]


# -- names and language ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "Outdoor temperature"),  # our curated English name
        ("cs", "Venkovní teplota"),  # our curated Czech name
        ("de", "Außentemperatur"),  # no curated German: Thermia's German text
    ],
)
async def test_entity_names_follow_the_home_assistant_language(
    hass: HomeAssistant, language: str, expected: str
) -> None:
    from custom_components.thermia_cloud.catalog.labels import load_bundled

    hass.config.language = language
    if language == "de":
        expected = load_bundled()["de-DE"]["REG_OPER_DATA_OUTDOOR_TEMP_MA_SA"]
    await setup(hass, make_entry(hass))
    assert name_of(hass, "sensor", OUTDOOR["registerIndex"]).endswith(expected)


async def test_device_names_fall_back_to_english_for_unknown_languages(
    hass: HomeAssistant,
) -> None:
    hass.config.language = "de"
    entry = make_entry(hass)
    await setup(hass, entry)
    child = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{INSTALLATION_ID}_circuit_1"), entry.entry_id
    )
    assert child.name == "Mixing circuit 1"


async def test_label_language_option_overrides_the_home_assistant_language(
    hass: HomeAssistant,
) -> None:
    hass.config.language = "en"
    entry = make_entry(hass, **{CONF_LABEL_LANGUAGE: "cs-CZ"})
    await setup(hass, entry)
    assert name_of(hass, "sensor", OUTDOOR["registerIndex"]).endswith("Venkovní teplota")
    child = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{INSTALLATION_ID}_circuit_1"), entry.entry_id
    )
    assert child.name == "Směšovací okruh 1"


async def test_names_step_saves_the_language(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "names"}
    )
    assert result["step_id"] == "names"
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LABEL_LANGUAGE: "de-DE"}
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_LABEL_LANGUAGE] == "de-DE"
    assert entry.state is ConfigEntryState.LOADED


# -- installations & registers -------------------------------------------------------------------


async def test_registers_step_selects_installations(hass: HomeAssistant, api: FakeApi) -> None:
    api.installation_ids = [42, 43]
    entry = make_entry(hass)
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "registers"}
    )
    assert result["step_id"] == "registers"
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_INSTALLATIONS: ["42", "43"], "show_hidden": True, CONF_EXPOSE_UNKNOWN: False},
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_INSTALLATIONS] == [42, 43] and entry.options["show_hidden"] is True
    registry = dr.async_get(hass)
    assert registry.async_get_device_by_identifier((DOMAIN, "43"), entry.entry_id)


async def test_registers_step_aborts_when_the_entry_is_not_running(hass: HomeAssistant) -> None:
    entry = make_entry(hass)  # never set up
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "registers"}
    )
    assert result["type"] == "abort" and result["reason"] == "entry_not_loaded"


# -- buttons -------------------------------------------------------------------------------------


def button(hass: HomeAssistant, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{INSTALLATION_ID}_{key}")
    assert eid, key
    return eid


async def test_refresh_names_downloads_filtered_texts_and_reloads(hass: HomeAssistant) -> None:
    hass.config.language = "de"
    entry = make_entry(hass)
    await setup(hass, entry)
    await hass.services.async_call(
        "button", "press", {"entity_id": button(hass, "refresh_names")}, blocking=True
    )
    await hass.async_block_till_done()
    stored = await Store(hass, 1, f"{DOMAIN}.labels.{entry.entry_id}").async_load()
    assert stored["culture"] == "de-DE"
    assert list(stored["labels"]) == ["REG_OPER_DATA_OUTDOOR_TEMP_MA_SA"]  # alarm text dropped
    assert name_of(hass, "sensor", OUTDOOR["registerIndex"]).endswith("Fresh outdoor text (de-DE)")


async def test_rediscover_reads_everything_again_and_reloads(
    hass: HomeAssistant, api: FakeApi
) -> None:
    entry = make_entry(hass)
    await setup(hass, entry)
    before = api.calls.count("get_history_registers")
    await hass.services.async_call(
        "button", "press", {"entity_id": button(hass, "rediscover")}, blocking=True
    )
    await hass.async_block_till_done()
    assert api.calls.count("get_history_registers") == before + 1
    assert entry.state is ConfigEntryState.LOADED


async def test_buttons_are_diagnostic_entities_on_the_main_device(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    await setup(hass, entry)
    registry = er.async_get(hass)
    for key in ("refresh_names", "rediscover"):
        reg = registry.async_get(button(hass, key))
        assert reg.entity_category == "diagnostic"


# -- Repair issues ---------------------------------------------------------------------------------


async def test_vanished_register_raises_an_issue_after_seven_days(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    entry = make_entry(hass)
    await setup(hass, entry)
    issues = ir.async_get(hass)
    api.hide.add("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    issue_id = f"register_vanished_{entry.entry_id}_{INSTALLATION_ID}"
    assert issues.async_get_issue(DOMAIN, issue_id) is None  # not yet: only just missing

    freezer.tick(timedelta(days=7, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue and not issue.is_fixable
    assert "REG_OPER_DATA_OUTDOOR_TEMP_MA_SA" in issue.translation_placeholders["registers"]

    api.hide.clear()  # the register is back
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_empty_discovery_raises_an_issue(hass: HomeAssistant, api: FakeApi) -> None:
    api.hide = {
        r["registerName"] for p in FIXTURES.glob("group_*.json") for r in json.loads(p.read_text())
    }
    entry = make_entry(hass)
    await setup(hass, entry)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"discovery_empty_{entry.entry_id}_{INSTALLATION_ID}"
    )


async def test_policy_acceptance_issue_is_raised_and_cleared(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    issue_id = f"policy_acceptance_required_{entry.entry_id}"
    with patch(
        "custom_components.thermia_cloud.async_build_client",
        side_effect=lambda *_: (None, FakeAuth(), _PolicyApi()),
    ):
        await setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)

    await hass.config_entries.async_reload(entry.entry_id)  # patched fake works again
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


class _PolicyApi(FakeApi):
    async def list_installations(self):  # type: ignore[no-untyped-def]
        raise PolicyAcceptanceError("terms")
