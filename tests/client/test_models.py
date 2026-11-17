from datetime import datetime

from custom_components.thermia_cloud.client.models import (
    RegisterSpec,
    RegisterValue,
    parse_timestamp,
)

from .conftest import load_group


def test_hot_water_operationmode_spec() -> None:
    raw = next(r for r in load_group("REG_GROUP_HOT_WATER") if r["registerId"] == 114185)
    spec = RegisterSpec.from_json(raw)
    assert spec.name == "REG_OPERATIONMODE"
    assert (spec.min_value, spec.max_value) == (0.0, 1.0)
    visible = {v.name: v.value for v in spec.value_names if v.visible}
    assert visible == {"Comfort": 0, "REG_VALUE_MODE_ECONOMY": 1, "Away": 2}


def test_value_and_naive_timestamp() -> None:
    raw = load_group("REG_GROUP_HOT_WATER")[1]
    value = RegisterValue.from_json(raw)
    assert value.timestamp == datetime(2024, 6, 26, 15, 51, 58, 410000)
    assert value.timestamp is not None and value.timestamp.tzinfo is None


def test_parse_timestamp_tolerates_garbage() -> None:
    assert parse_timestamp(None) is None
    assert parse_timestamp("not a date") is None


def test_all_fixture_registers_parse() -> None:
    from .conftest import FIXTURES

    total = 0
    for path in FIXTURES.glob("group_*.json"):
        for raw in load_group(path.stem.removeprefix("group_")):
            RegisterSpec.from_json(raw)
            RegisterValue.from_json(raw)
            total += 1
    assert total == 26


def test_model_comes_from_the_profile_when_the_account_gives_none() -> None:
    from custom_components.thermia_cloud.client.models import Installation

    item = {"id": 1, "name": "x", "model": "", "isOnline": True,
            "profile": {"id": 1005, "name": "IQ", "thermiaName": "iTec"}}  # fmt: skip
    installation = Installation.from_json(item)
    assert (installation.model, installation.model_id) == ("iTec", "IQ")
    assert Installation.from_json({**item, "model": "Own"}).model == "Own"  # an explicit model wins
    assert Installation.from_json({"id": 2, "isOnline": False}).model == ""  # no profile at all
