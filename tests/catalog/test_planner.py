import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.thermia_cloud.catalog.loader import load_catalog, parse_catalog
from custom_components.thermia_cloud.catalog.planner import (
    EntityPlan,
    PlannerOptions,
    build_plan,
    resolve_name_collisions,
)
from custom_components.thermia_cloud.catalog.units import (
    bracket_unit,
    resolve_unit,
    strip_unit_bracket,
)
from custom_components.thermia_cloud.client.models import (
    HistoryRegister,
    RegisterSpec,
    RegisterValue,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "itec_profile_1005"
NOW = datetime(2026, 11, 17, 12, 0)


def load_registers() -> list[tuple[RegisterSpec, RegisterValue]]:
    out = []
    for path in sorted(FIXTURES.glob("group_*.json")):
        for raw in json.loads(path.read_text()):
            out.append((RegisterSpec.from_json(raw), RegisterValue.from_json(raw)))
    return out


def load_history() -> dict[int, HistoryRegister]:
    data = json.loads((FIXTURES / "history_registers.json").read_text())
    return {r.register_index: r for r in map(HistoryRegister.from_json, data["registers"])}


@pytest.fixture(scope="module")
def plan():  # type: ignore[no-untyped-def]
    return build_plan(load_registers(), load_catalog(), history=load_history(), now=NOW)


def by_name(plan, name: str, group: str | None = None) -> list[EntityPlan]:  # type: ignore[no-untyped-def]
    return [
        e
        for e in plan.entities
        if e.register_name == name and (group is None or e.group_name == group)
    ]


GOLDEN = Path(__file__).parent / "golden"


def assert_golden(name: str, data: object) -> None:
    """Compare with ``golden/<name>.json``; run with ``UPDATE_GOLDEN=1`` to rewrite it.

    Plain JSON instead of a snapshot library: readable in a pull request and the same on every
    platform.
    """
    actual = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False, default=list) + "\n"
    path = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == actual, f"{name} changed (UPDATE_GOLDEN=1 to accept)"


def test_itec_plan_matches_the_golden_file(plan) -> None:  # type: ignore[no-untyped-def]
    assert_golden("itec_plan", [asdict(e) for e in plan.entities])
    assert_golden("itec_plan_notes", [asdict(n) for n in plan.notes])


def test_hot_water_mode_uses_visible_values(plan) -> None:  # type: ignore[no-untyped-def]
    [hot] = by_name(plan, "REG_OPERATIONMODE", "REG_GROUP_HOT_WATER")
    assert hot.platform == "select"
    assert hot.options == ((0, "Comfort"), (1, "REG_VALUE_MODE_ECONOMY"), (2, "Away"))


def test_operation_mode_is_a_select_with_heating_risk(plan) -> None:  # type: ignore[no-untyped-def]
    [op] = by_name(plan, "REG_OPERATIONMODE", "REG_GROUP_OPERATIONAL_OPERATION")
    assert op.platform == "select" and op.risk == "heating" and op.writable
    assert [v for v, _ in op.options] == [0, 1, 2, 3, 4]


def test_hot_water_status_is_a_switch(plan) -> None:  # type: ignore[no-untyped-def]
    [e] = by_name(plan, "REG_HOT_WATER_STATUS")
    assert e.platform == "switch" and e.default_enabled


def test_status_flags_visible_enabled_hidden_as_disabled_diagnostics(plan) -> None:  # type: ignore[no-untyped-def]
    flags = {f.flag_value: f for f in by_name(plan, "COMP_STATUS_ITEC")}
    assert all(f.platform == "binary_sensor" and not f.flag_equality for f in flags.values())
    assert {1, 8, 16, 32} <= set(flags)
    assert all(flags[v].default_enabled for v in (1, 8, 16, 32))
    # radiator pump (2), pool (64) and cooling (128) are hidden by the cloud: offered, but off
    for hidden in (2, 64, 128):
        assert not flags[hidden].default_enabled
        assert flags[hidden].entity_category == "diagnostic"
    assert len({f.key for f in flags.values()}) == len(flags)


def test_keys_follow_decision_d10(plan) -> None:  # type: ignore[no-untyped-def]
    [flag1] = [e for e in by_name(plan, "COMP_STATUS_ITEC") if e.flag_value == 1]
    assert flag1.key == f"{flag1.register_index}_1"
    [curve] = by_name(plan, "REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE")
    assert curve.key == str(curve.register_index) != str(curve.register_id)
    assert len({e.key for e in plan.entities}) == len(plan.entities)


def test_hidden_register_creates_nothing(plan) -> None:  # type: ignore[no-untyped-def]
    assert by_name(plan, "COMP_HAS_LINK") == []


def test_curves_per_circuit_device(plan) -> None:  # type: ignore[no-untyped-def]
    [main] = by_name(plan, "REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE")
    [circ1] = by_name(plan, "REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE_CIRC1")
    assert (main.device, circ1.device) == ("main", "circuit_1")
    assert main.key != circ1.key
    assert (main.min_value, main.max_value, main.number_mode) == (22.0, 56.0, "slider")
    assert main.risk == "heating"


def test_stale_register_is_created_disabled(plan) -> None:  # type: ignore[no-untyped-def]
    [indoor] = by_name(plan, "REG_INDOOR_TEMPERATURE")
    assert indoor.stale and not indoor.default_enabled
    [outdoor] = by_name(plan, "REG_OPER_DATA_OUTDOOR_TEMP_MA_SA")
    assert not outdoor.stale and outdoor.default_enabled


def test_old_timestamp_does_not_disable_settings(plan) -> None:  # type: ignore[no-untyped-def]
    [mode] = by_name(plan, "REG_OPERATIONMODE", "REG_GROUP_HOT_WATER")
    assert mode.writable and not mode.stale  # last changed in 2024, still a live setting
    assert mode.default_enabled


def test_value_based_condition_and_disabled_value(plan) -> None:  # type: ignore[no-untyped-def]
    [hw] = by_name(plan, "REG_HOT_WATER_TEMPERATURE")
    assert hw.runtime_condition == "{REG_HOT_WATER_TEMPERATURE} > 0"
    assert hw.disabled_value == -100


def test_unresolved_structural_reference_keeps_entity_and_is_noted(plan) -> None:  # type: ignore[no-untyped-def]
    assert by_name(plan, "REG_OPER_TIME_IMM1")
    assert ("unresolved_reference", "REG_OPER_TIME_IMM1", "REG_SER_AUX_HEAT_MAX_STEP") in {
        (n.code, n.register, n.detail) for n in plan.notes
    }


def test_operating_hours_are_diagnostic_totals(plan) -> None:  # type: ignore[no-untyped-def]
    [hours] = by_name(plan, "REG_OPER_TIME_COMPRESSOR")
    assert (hours.unit, hours.state_class, hours.entity_category) == (
        "h",
        "total_increasing",
        "diagnostic",
    )


def test_distribution_sensor_belongs_to_circuit_1(plan) -> None:  # type: ignore[no-untyped-def]
    [e] = by_name(plan, "REG_OPER_DATA_DISTR_CIR1")
    assert e.device == "circuit_1" and e.platform == "sensor"


def _with_condition(text: str):  # type: ignore[no-untyped-def]
    history = load_history()
    heat_stop = next(s for s, _ in load_registers() if s.name == "REG_HEATING_HEAT_STOP")
    history[heat_stop.register_index] = HistoryRegister(
        heat_stop.register_index, heat_stop.name, text, None, None
    )
    return history


def test_false_structural_condition_hides_unless_show_hidden() -> None:
    history = _with_condition("{REG_HOT_WATER_STATUS} = 5")
    plan = build_plan(load_registers(), load_catalog(), history=history, now=NOW)
    assert by_name(plan, "REG_HEATING_HEAT_STOP") == []
    assert any(n.code == "hidden_by_condition" for n in plan.notes)
    shown = build_plan(
        load_registers(), load_catalog(), history=history, now=NOW,
        options=PlannerOptions(show_hidden=True),
    )  # fmt: skip
    assert by_name(shown, "REG_HEATING_HEAT_STOP")


def test_unparsable_condition_is_noted_and_entity_kept() -> None:
    plan = build_plan(load_registers(), load_catalog(), history=_with_condition("{A} >>"), now=NOW)
    assert by_name(plan, "REG_HEATING_HEAT_STOP")
    assert any(n.code == "condition_unparsable" for n in plan.notes)


def test_generic_rules_without_catalog() -> None:
    plan = build_plan(
        load_registers(), parse_catalog("version: 1\ndevices: {main: {}}\nregisters: {}\n"),
        history=load_history(), now=NOW,
    )  # fmt: skip
    assert plan.entities and not any(e.default_enabled for e in plan.entities)
    [toph] = by_name(plan, "REG_SER_HOT_WATER_TOPH_INTER")
    assert toph.platform == "sensor" and toph.risk == "service"  # REG_SER_* is read-only
    [curve] = by_name(plan, "REG_HEATING_HEAT_CURVE", "REG_GROUP_HEATING_CURVE")
    assert curve.platform == "number" and curve.unit == "°C"  # from the modifier
    [status] = by_name(plan, "REG_HOT_WATER_STATUS")
    assert status.platform == "switch"


def test_readonly_register_cannot_become_writable_via_catalog() -> None:
    catalog = parse_catalog(
        "version: 1\ndevices: {main: {}}\n"
        "registers:\n  REG_OPER_DATA_SUPPLY_MA_SA: {kind: number}\n"
    )
    plan = build_plan(load_registers(), catalog, now=NOW)
    [e] = by_name(plan, "REG_OPER_DATA_SUPPLY_MA_SA")
    assert e.platform == "sensor" and not e.writable
    assert any(n.code == "catalog_kind_incompatible" for n in plan.notes)


def test_name_collision_pass() -> None:
    a = replace(_dummy(), key="1", platform="sensor", group_name="G1")
    b = replace(_dummy(), key="2", platform="binary_sensor", group_name="G2")
    c = replace(_dummy(), key="3", platform="sensor", group_name="G3", device="circuit_1")
    names = resolve_name_collisions([a, b, c], lambda p: "Hot water")
    assert names["1"] != names["2"] and names["3"] == "Hot water"


def _dummy() -> EntityPlan:
    return EntityPlan(
        platform="sensor",
        key="0",
        register_id=0,
        register_index=0,
        register_name="R",
        group_name="G",
        device="main",
        label_key="R",
        translation_key=None,
        description_key=None,
        unit=None,
        device_class=None,
        state_class=None,
        entity_category=None,
        icon=None,
        default_enabled=False,
        stale=False,
        risk="none",
        writable=False,
    )


def test_unit_resolution_order() -> None:
    assert resolve_unit("kW", 8, "Power [°C]") == "kW"  # catalog first
    assert resolve_unit(None, 8, "x") == "°C"  # then modifier
    assert resolve_unit(None, 0, "Curve [°C]") == "°C"  # then en-US bracket
    assert resolve_unit(None, 0, "Zone (system)") is None
    assert bracket_unit("Zone [foo]") is None
    assert strip_unit_bracket("Curve [°C]") == "Curve"
    assert strip_unit_bracket("Zone [foo]") == "Zone [foo]"


# Safety regression (roadmap P5.8, DECISIONS D6): which registers can be written, how risky they
# are and which are enabled out of the box. Changing this table means changing the safety story.
WRITABLE = {
    ("REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_CURVE"): ("number", "heating", True),
    ("REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_CURVE_MIN"): ("number", "heating", False),
    ("REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_CURVE_MAX"): ("number", "heating", False),
    ("REG_GROUP_HEATING_CURVE", "REG_HEATING_HEAT_STOP"): ("number", "heating", False),
    ("REG_GROUP_HEATING_CURVE_CIRC1", "REG_ACTIVATE_CIRC1"): ("select", "heating", False),
    ("REG_GROUP_HEATING_CURVE_CIRC1", "REG_HEATING_HEAT_CURVE"): ("number", "heating", True),
    ("REG_GROUP_HEATING_CURVE_CIRC1", "REG_HEATING_HEAT_CURVE_MIN"): ("number", "heating", False),
    ("REG_GROUP_HEATING_CURVE_CIRC1", "REG_HEATING_HEAT_CURVE_MAX"): ("number", "heating", False),
    ("REG_GROUP_HOT_WATER", "REG_HOT_WATER_STATUS"): ("switch", "none", True),
    ("REG_GROUP_HOT_WATER", "REG_OPERATIONMODE"): ("select", "none", True),
    ("REG_GROUP_HOT_WATER", "REG_SER_HOT_WATER_TOPH_INTER"): ("number", "none", False),
    ("REG_GROUP_OPERATIONAL_OPERATION", "REG_OPERATIONMODE"): ("select", "heating", True),
}


def test_writable_entities_match_the_safety_table(plan) -> None:  # type: ignore[no-untyped-def]
    actual = {
        (e.group_name, e.register_name): (e.platform, e.risk, e.default_enabled)
        for e in plan.entities
        if e.writable
    }
    assert actual == WRITABLE


def test_installer_level_registers_are_never_enabled_by_default(plan) -> None:  # type: ignore[no-untyped-def]
    disabled = {"REG_HEATING_HEAT_CURVE_MIN", "REG_HEATING_HEAT_CURVE_MAX", "REG_HEATING_HEAT_STOP",
                "REG_ACTIVATE_CIRC1", "REG_SER_HOT_WATER_TOPH_INTER"}  # fmt: skip
    assert all(not e.default_enabled for e in plan.entities if e.register_name in disabled)


def test_constant_mode_register_becomes_an_enabled_number_on_circuit_1() -> None:
    """In *Constant* mode the cloud returns REG_HEATING_HEAT_CURVE1_CONSTANT instead of the curve
    registers. The fixture is rebuilt from the real response of 2026-11-17 (id, index, limits,
    modifier, value and timestamps as recorded; the remaining fields copied from a sibling)."""
    raw = json.loads(
        (FIXTURES / "mode_constant_group_REG_GROUP_HEATING_CURVE_CIRC1.json").read_text()
    )
    registers = [(RegisterSpec.from_json(r), RegisterValue.from_json(r)) for r in raw]
    plan = build_plan(registers, load_catalog(), now=NOW)
    by = {e.register_name: e for e in plan.entities}
    assert set(by) == {
        "REG_ACTIVATE_CIRC1",
        "REG_HEATING_HEAT_CURVE1_CONSTANT",
    }  # no curve registers
    constant = by["REG_HEATING_HEAT_CURVE1_CONSTANT"]
    assert constant.platform == "number" and constant.device == "circuit_1"
    assert (constant.unit, constant.risk, constant.default_enabled) == ("°C", "heating", True)
    assert (constant.min_value, constant.max_value, constant.step) == (20.0, 55.0, 1.0)
    assert constant.translation_key == "constant_temperature"


def test_a_suffix_that_repeats_the_name_is_replaced() -> None:
    a = replace(_dummy(), key="1", platform="switch", group_name="G_HOT")
    b = replace(_dummy(), key="2", platform="binary_sensor", group_name="G_STATUS")
    names = resolve_name_collisions(
        [a, b],
        lambda p: "Hot water",
        lambda p: "Hot water" if p.group_name == "G_HOT" else "Status",
    )
    assert names["1"] == "Hot water (switch)" and names["2"] == "Hot water (Status)"


def test_indoor_temperature_is_skipped_when_the_pump_has_no_indoor_sensor() -> None:
    plan = build_plan(
        load_registers(), load_catalog(), now=NOW, options=PlannerOptions(has_indoor_sensor=False)
    )
    assert by_name(plan, "REG_INDOOR_TEMPERATURE") == []
    assert any(n.code == "no_indoor_sensor" for n in plan.notes)
    unknown = build_plan(load_registers(), load_catalog(), now=NOW)
    assert by_name(unknown, "REG_INDOOR_TEMPERATURE")  # status unknown: nothing is hidden


def _synthetic(name: str, **fields: object) -> tuple[RegisterSpec, RegisterValue]:
    """A register in the style of the iTec fixture, with fields overridden."""
    base = json.loads((FIXTURES / "group_REG_GROUP_HEATING_CURVE.json").read_text())[0]
    raw = {
        **base,
        "registerName": name,
        "registerId": 9_000_001,
        "registerIndex": 9_000_001,
        "timeStamp": "2026-11-17T11:00:00",
        **fields,
    }
    return RegisterSpec.from_json(raw), RegisterValue.from_json(raw)


@pytest.mark.parametrize(
    "name",
    [
        "REG_HEATING_ROOM_FACTOR",
        "REG_ROOM_FACTOR",
        "REG_HEATING_CURVE_PLUS5",
        "REG_HEATING_CURVE_0",
        "REG_HEATING_CURVE_MINUS5",
        "REG_CURVE_MINUS_5",
    ],
)
def test_modifier_1_registers_that_are_not_temperatures_stay_unitless(name: str) -> None:
    plan = build_plan(
        [_synthetic(name, modifier=1, minValue=-5.0, maxValue=5.0)], load_catalog(), now=NOW
    )
    [entity] = plan.entities
    assert entity.platform == "number" and entity.unit is None and entity.device_class is None
    assert entity.risk == "heating" and not entity.default_enabled
    # the same modifier on an unknown register still means degrees
    [unknown] = build_plan(
        [_synthetic("REG_X_UNKNOWN", modifier=1)], load_catalog(), now=NOW
    ).entities
    assert unknown.unit == "°C"


@pytest.mark.parametrize("name", ["REG_HOT_WATER_BOOST", "REG__HOT_WATER_BOOST"])
def test_hot_water_boost_is_a_switch_under_both_spellings(name: str) -> None:
    boost = _synthetic(
        name,
        presentation="Enumeration",
        minValue=0.0,
        maxValue=1.0,
        valueNames=[
            {
                "name": "REG_VALUE_STATUS_OFF",
                "value": 0,
                "visible": True,
                "isReadonly": False,
                "confirmation": None,
            },
            {
                "name": "REG_VALUE_STATUS_ON",
                "value": 1,
                "visible": True,
                "isReadonly": False,
                "confirmation": None,
            },
        ],
    )
    [entity] = build_plan([boost], load_catalog(), now=NOW).entities
    assert entity.platform == "switch" and entity.default_enabled
    assert entity.translation_key == "hot_water_boost" and entity.risk == "none"


def test_display_precision_is_capped_at_two_decimals() -> None:
    odd = _synthetic("REG_X_FRACTIONAL", presentation="Integer", isReadOnly=True, step=0.0167)
    [entity] = build_plan([odd], load_catalog(), now=NOW).entities
    assert entity.platform == "sensor" and entity.display_precision == 2
