import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

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


def test_itec_snapshot(plan, snapshot: SnapshotAssertion) -> None:  # type: ignore[no-untyped-def]
    rows = [asdict(e) for e in plan.entities]
    assert rows == snapshot
    assert [asdict(n) for n in plan.notes] == snapshot(name="notes")


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


def test_status_flags_only_visible_bits(plan) -> None:  # type: ignore[no-untyped-def]
    flags = by_name(plan, "COMP_STATUS_ITEC")
    assert flags and all(f.platform == "binary_sensor" and not f.flag_equality for f in flags)
    assert 2 not in {f.flag_value for f in flags}  # radiator pump bit is hidden
    assert {f.flag_value for f in flags} >= {1, 8, 16}
    assert len({f.key for f in flags}) == len(flags)


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
