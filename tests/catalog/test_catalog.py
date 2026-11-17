import json
from pathlib import Path

import pytest

from custom_components.thermia_cloud.catalog.loader import (
    CatalogError,
    ambiguous_plain_keys,
    async_load_catalog,
    load_catalog,
    parse_catalog,
)
from custom_components.thermia_cloud.catalog.schema import Category, Kind, Risk

FIXTURES = Path(__file__).parent.parent / "fixtures" / "itec_profile_1005"


def fixture_pairs() -> list[tuple[str, str]]:
    return [
        (reg["groupName"], reg["registerName"])
        for path in FIXTURES.glob("group_*.json")
        for reg in json.loads(path.read_text())
    ]


def test_shipped_catalog_loads() -> None:
    catalog = load_catalog()
    assert catalog.registers["REG_PID"].default_enabled is False
    assert catalog.registers["COMP_HAS_LINK"].kind is Kind.SKIP


async def test_async_loader() -> None:
    assert (await async_load_catalog()).devices["circuit_1"].translation_key == "device_circuit_1"


def test_every_fixture_register_is_curated() -> None:
    catalog = load_catalog()
    missing = [(g, n) for g, n in fixture_pairs() if catalog.lookup(g, n) is None]
    assert missing == []


def test_no_plain_key_silently_matches_two_groups() -> None:
    assert ambiguous_plain_keys(load_catalog(), fixture_pairs()) == []


def test_ambiguity_check_catches_plain_operationmode() -> None:
    catalog = parse_catalog(
        "version: 1\ndevices: {main: {}}\nregisters:\n  REG_OPERATIONMODE: {kind: select}\n"
    )
    assert ambiguous_plain_keys(catalog, fixture_pairs()) == ["REG_OPERATIONMODE"]


def test_group_slash_name_wins_over_plain_name() -> None:
    catalog = load_catalog()
    hot = catalog.lookup("REG_GROUP_HOT_WATER", "REG_OPERATIONMODE")
    ops = catalog.lookup("REG_GROUP_OPERATIONAL_OPERATION", "REG_OPERATIONMODE")
    assert hot is not None and ops is not None
    assert hot.translation_key == "hot_water_mode"
    assert ops.risk is Risk.HEATING
    assert catalog.lookup("REG_GROUP_TEMPERATURES", "REG_OPERATIONMODE") is None


def test_device_and_category_resolution() -> None:
    catalog = load_catalog()
    curve = catalog.lookup("REG_GROUP_HEATING_CURVE_CIRC1", "REG_HEATING_HEAT_CURVE")
    assert catalog.device_for("REG_GROUP_HEATING_CURVE_CIRC1", curve) == "circuit_1"
    assert catalog.device_for("REG_GROUP_HOT_WATER") == "main"  # unlisted group
    distr = catalog.lookup("REG_GROUP_TEMPERATURES", "REG_OPER_DATA_DISTR_CIR1")
    assert catalog.device_for("REG_GROUP_TEMPERATURES", distr) == "circuit_1"  # per-register
    hours = catalog.lookup("REG_GROUP_OPERATIONAL_TIME", "REG_OPER_TIME_IMM1")
    assert catalog.category_for("REG_GROUP_OPERATIONAL_TIME", hours) is Category.DIAGNOSTIC


@pytest.mark.parametrize(
    "text",
    [
        "version: 2\ndevices: {main: {}}\nregisters: {}\n",
        "version: 1\ndevices: {main: {}}\nregisters:\n  A: {kind: bogus}\n",
        "version: 1\ndevices: {main: {}}\nregisters:\n  A: {kind: sensor, risk: scary}\n",
        "version: 1\ndevices: {main: {}}\nregisters:\n  A: {kind: sensor, device: nowhere}\n",
        "version: 1\ndevices: {main: {}}\ngroups:\n  G: {device: nowhere}\nregisters: {}\n",
        "version: 1\ndevices: {main: {}}\nregisters:\n  A: {kind: sensor, typo: 1}\n",
        "{",
    ],
)
def test_invalid_catalogs_are_rejected(text: str) -> None:
    with pytest.raises(CatalogError):
        parse_catalog(text)
