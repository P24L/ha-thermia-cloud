import json

import pytest

from custom_components.thermia_cloud.client.visibility import (
    RegisterLookup,
    VisibilityParseError,
    evaluate_node,
    parse_condition,
)

from .conftest import FIXTURES


def values(**kw: float | None):  # type: ignore[no-untyped-def]
    return lambda name: kw.get(name)


@pytest.mark.parametrize(
    ("text", "regs", "visible"),
    [
        ("{A} >= 0", {"A": 0.0}, True),
        ("{A} >= 0", {"A": -1.0}, False),
        ("{A} > 0", {"A": 0.0}, False),
        ("{A} = 1", {"A": 1.0}, True),
        ("{A} = 1", {"A": 2.0}, False),
        ("{A} != 1", {"A": 2.0}, True),
        ("{A} <> 1", {"A": 1.0}, False),
        ("{A} <= 3", {"A": 3.0}, True),
        ("{A} < 3", {"A": 3.0}, False),
        ("{A} > 0 AND {A} < 65535", {"A": 650.0}, True),
        ("{A} > 0 AND {A} < 65535", {"A": 65535.0}, False),
        ("{A} > 0 and {A} < 5", {"A": 2.0}, True),
        ("{A} = 1 OR {B} = 1", {"A": 0.0, "B": 1.0}, True),
        ("{A} = 1 OR {B} = 1", {"A": 0.0, "B": 0.0}, False),
        ("({A} = 1 OR {B} = 1) AND {C} > 0", {"A": 1.0, "B": 0.0, "C": 0.0}, False),
        (
            "{A} = 1 OR {B} = 1 AND {C} > 0",
            {"A": 1.0, "B": 0.0, "C": 0.0},
            True,
        ),  # AND binds tighter
        ("{A} > -100", {"A": -50.0}, True),
        ("0 < {A}", {"A": 1.0}, True),
    ],
)
def test_evaluation(text: str, regs: dict[str, float], visible: bool) -> None:
    assert parse_condition(text).evaluate(values(**regs)).visible is visible


def test_unresolved_reference_is_visible_and_reported() -> None:
    result = parse_condition("{REG_SER_AUX_HEAT_MAX_STEP} >= 1").evaluate(values())
    assert result.visible is True
    assert result.unresolved == {"REG_SER_AUX_HEAT_MAX_STEP"}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{A}",
        "{A} >",
        "{A} >> 1",
        "{A} > 1 AND",
        "({A} > 1",
        "{A} > 1)",
        "A > 1",
        "{A} > 1 XOR {B} > 1",
    ],
)
def test_malformed_conditions(text: str) -> None:
    with pytest.raises(VisibilityParseError):
        parse_condition(text)


def test_every_condition_in_the_fixture_parses() -> None:
    data = json.loads((FIXTURES / "history_registers.json").read_text())
    conditions = [
        r["registerVisibilityCondition"]
        for r in data["registers"]
        if r["registerVisibilityCondition"]
    ]
    assert len(conditions) == 9
    for text in conditions:
        assert parse_condition(text).refs


def test_split_structural_vs_value_based() -> None:
    own = parse_condition("{REG_OPER_TIME_HOT_WATER} > 0 AND {REG_OPER_TIME_HOT_WATER} < 65535")
    assert own.split("REG_OPER_TIME_HOT_WATER")[0] is None
    assert own.split("REG_OPER_TIME_HOT_WATER")[1] is not None

    other = parse_condition("{REG_SER_AUX_HEAT_MAX_STEP} >= 1")
    structural, value = other.split("REG_OPER_TIME_IMM1")
    assert structural is not None and value is None

    mixed = parse_condition("{REG_X} > 0 AND {REG_OTHER} = 1")
    structural, value = mixed.split("REG_X")
    assert evaluate_node(structural, values(REG_OTHER=0.0)).visible is False
    assert evaluate_node(value, values(REG_X=-5.0)).visible is False
    assert evaluate_node(None, values()).visible is True


def test_mixed_or_stays_value_based() -> None:
    structural, value = parse_condition("{REG_X} > 0 OR {REG_OTHER} = 1").split("REG_X")
    assert structural is None and value is not None


def test_lookup_prefers_own_group_and_flags_ambiguity() -> None:
    lookup = RegisterLookup(
        [
            ("MAIN", "REG_CURVE", 22.0),
            ("CIRC1", "REG_CURVE", 30.0),
            ("MAIN", "REG_UNIQUE", 5.0),
        ]
    )
    assert lookup.resolver("CIRC1")("REG_CURVE") == 30.0
    assert lookup.resolver("OTHER")("REG_UNIQUE") == 5.0
    assert lookup.ambiguous == set()
    assert lookup.resolver("OTHER")("REG_CURVE") is None
    assert lookup.ambiguous == {"REG_CURVE"}
    assert lookup.resolver("MAIN")("REG_MISSING") is None
