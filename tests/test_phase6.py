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
        ("de", "Außentemperatur"),  # our curated German name
        ("pt", "Outdoor temperature"),  # no Portuguese anywhere: our English name
    ],
)
async def test_entity_names_follow_the_home_assistant_language(
    hass: HomeAssistant, language: str, expected: str
) -> None:
    hass.config.language = language
    await setup(hass, make_entry(hass))
    assert name_of(hass, "sensor", OUTDOOR["registerIndex"]).endswith(expected)


async def test_device_names_fall_back_to_english_for_unknown_languages(
    hass: HomeAssistant,
) -> None:
    hass.config.language = "pt"
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
        {
            "installations": {CONF_INSTALLATIONS: ["42", "43"]},
            "visibility": {"show_hidden": True, CONF_EXPOSE_UNKNOWN: False},
        },
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
    assert entry.state is ConfigEntryState.LOADED  # reloaded with the stored texts


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


# -- generic sensor kinds (not covered by the iTec catalog) ---------------------------

BASE = register("REG_OPER_DATA_OUTDOOR_TEMP_MA_SA", "REG_GROUP_TEMPERATURES")


def extra_register(register_id: int, name: str, **fields: object) -> dict:
    return {**BASE, "registerId": register_id, "registerIndex": register_id, "registerName": name,
            "isReadOnly": True, "modifier": 0, **fields}  # fmt: skip


def _value_name(name: str, value: int, visible: bool) -> dict:
    return {
        "name": name,
        "value": value,
        "visible": visible,
        "isReadonly": True,
        "confirmation": None,
    }


async def test_generic_timestamp_enum_and_precision_sensors(
    hass: HomeAssistant, api: FakeApi
) -> None:
    api.extra = [
        extra_register(9990001, "REG_X_TIME", presentation="PosixTime", registerValue=1767225600.0),
        extra_register(
            9990002,
            "REG_X_MODE",
            presentation="Enumeration",
            registerValue=2.0,
            valueNames=[
                {
                    "name": "REG_VALUE_STATUS_OFF",
                    "value": 0,
                    "visible": False,
                    "isReadonly": True,
                    "confirmation": None,
                },
                {
                    "name": "REG_VALUE_MODE_ECONOMY",
                    "value": 2,
                    "visible": True,
                    "isReadonly": True,
                    "confirmation": None,
                },
            ],
        ),
        extra_register(9990003, "REG_X_PRECISE", step=0.1, registerValue=1.5),
    ]
    entry = make_entry(hass)
    await setup(hass, entry)
    registry = er.async_get(hass)
    for number in (9990001, 9990002, 9990003):
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"{INSTALLATION_ID}_{number}")
        assert eid and registry.async_get(eid).disabled_by  # unknown registers start disabled
        registry.async_update_entity(eid, disabled_by=None)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=45))
    await hass.async_block_till_done()

    def state(number: int):  # type: ignore[no-untyped-def]
        return hass.states.get(
            registry.async_get_entity_id("sensor", DOMAIN, f"{INSTALLATION_ID}_{number}")
        )

    assert state(9990001).state == "2026-01-01T00:00:00+00:00"
    assert state(9990002).state == "economy" and state(9990002).attributes["options"] == ["economy"]
    assert state(9990003).state == "1.5"
    assert (
        registry.async_get(state(9990003).entity_id).options["sensor"][
            "suggested_display_precision"
        ]
        == 1
    )


async def test_unknown_registers_can_be_left_out(hass: HomeAssistant, api: FakeApi) -> None:
    api.extra = [extra_register(9990009, "REG_X_UNKNOWN")]
    await setup(hass, make_entry(hass, **{CONF_EXPOSE_UNKNOWN: False}))
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{INSTALLATION_ID}_9990009")
        is None
    )


async def test_registers_step_aborts_when_the_cloud_is_unreachable(
    hass: HomeAssistant, api: FakeApi
) -> None:
    from custom_components.thermia_cloud.client.errors import NetworkError

    entry = make_entry(hass)
    await setup(hass, entry)
    api.error = NetworkError("down")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "registers"}
    )
    assert result["type"] == "abort" and result["reason"] == "cannot_connect"


async def test_status_flags_have_clear_unique_names(hass: HomeAssistant) -> None:
    hass.config.language = "cs"
    await setup(hass, make_entry(hass))
    names = [
        state.attributes["friendly_name"]
        for state in hass.states.async_all()
        if state.entity_id.startswith(
            ("binary_sensor.", "switch.", "sensor.", "number.", "select.")
        )
        and state.attributes.get("friendly_name", "").startswith("Test installation")
    ]
    assert len(names) == len(set(names))
    assert not [
        n for n in names if n.endswith(")") and n.split(" (")[0].endswith(n.rsplit("(", 1)[-1][:-1])
    ]
    flags = {
        s.attributes["friendly_name"]
        for s in hass.states.async_all("binary_sensor")
        if s.attributes.get("friendly_name", "").startswith("Test installation")
    }
    assert {
        "Test installation 42 Ohřev teplé vody",
        "Test installation 42 Kompresor v provozu",
    } <= flags


async def test_no_indoor_sensor_means_no_indoor_entity(hass: HomeAssistant, api: FakeApi) -> None:
    indoor = register("REG_INDOOR_TEMPERATURE", "REG_GROUP_TEMPERATURES")["registerIndex"]
    api.has_indoor_sensor = False  # status: hasIndoorTempSensor = false
    await setup(hass, make_entry(hass))
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{INSTALLATION_ID}_{indoor}")
        is None
    )


async def test_indoor_entity_exists_with_a_sensor_or_unknown_status(
    hass: HomeAssistant, api: FakeApi
) -> None:
    indoor = register("REG_INDOOR_TEMPERATURE", "REG_GROUP_TEMPERATURES")["registerIndex"]
    api.has_indoor_sensor = None  # status unreadable / key missing: do not hide anything
    await setup(hass, make_entry(hass))
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{INSTALLATION_ID}_{indoor}")


# -- entities disabled earlier by the integration -------------------------------------------------


def _preregister(hass: HomeAssistant, entry: MockConfigEntry, register_index: int, by) -> str:  # type: ignore[no-untyped-def]
    return (
        er.async_get(hass)
        .async_get_or_create(
            "sensor",
            DOMAIN,
            f"{INSTALLATION_ID}_{register_index}",
            config_entry=entry,
            disabled_by=by,
        )
        .entity_id
    )


async def test_integration_disabled_entities_are_enabled_when_the_plan_enables_them(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(hass)
    imm1 = register("REG_OPER_TIME_IMM1", "REG_GROUP_OPERATIONAL_TIME")["registerIndex"]
    eid = _preregister(hass, entry, imm1, er.RegistryEntryDisabler.INTEGRATION)  # catalog was older
    await setup(hass, entry)
    assert er.async_get(hass).async_get(eid).disabled_by is None
    assert hass.states.get(eid).state == "138.0"


async def test_entities_the_user_disabled_stay_disabled(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    imm1 = register("REG_OPER_TIME_IMM1", "REG_GROUP_OPERATIONAL_TIME")["registerIndex"]
    eid = _preregister(hass, entry, imm1, er.RegistryEntryDisabler.USER)
    await setup(hass, entry)
    assert er.async_get(hass).async_get(eid).disabled_by is er.RegistryEntryDisabler.USER
    assert hass.states.get(eid) is None
