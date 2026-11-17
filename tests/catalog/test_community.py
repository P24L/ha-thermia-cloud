"""Planner behaviour on dumps of other model families.

The dumps come from the python-thermia-online-api project (see NOTICE.md) and were taken with the
*older* Thermia app/cloud, before the change of September 2026. They show how other families
look; they are no authority for what the cloud returns today (the iTec dump of 2024 already
differs from the live one).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.thermia_cloud.catalog.loader import load_catalog
from custom_components.thermia_cloud.catalog.planner import build_plan
from custom_components.thermia_cloud.client.models import RegisterSpec, RegisterValue

from .golden import assert_golden

COMMUNITY = Path(__file__).parent.parent / "fixtures" / "community"
NAMES = sorted(p.name for p in COMMUNITY.iterdir() if p.is_dir())
PLATFORMS = {"sensor", "binary_sensor", "number", "select", "switch"}


def load(name: str) -> tuple[list[tuple[RegisterSpec, RegisterValue]], datetime]:
    pairs = []
    for path in sorted((COMMUNITY / name).glob("group_*.json")):
        for raw in json.loads(path.read_text()):
            pairs.append((RegisterSpec.from_json(raw), RegisterValue.from_json(raw)))
    newest = max(v.timestamp for _, v in pairs if v.timestamp)
    return pairs, newest + timedelta(hours=1)  # judge staleness as of the dump, not as of today


def plan_of(name: str):  # type: ignore[no-untyped-def]
    pairs, now = load(name)
    return build_plan(pairs, load_catalog(), now=now)


def test_there_are_six_community_dumps() -> None:
    assert NAMES == [
        "atec_dhp_aq",
        "diplomat_duo_921",
        "diplomat_duo_921_heating",
        "itec_iq",
        "ncp_1024",
        "ncp_1028",
    ]


@pytest.mark.parametrize("name", NAMES)
def test_every_dump_plans_without_collisions(name: str) -> None:
    plan = plan_of(name)
    keys = [e.key for e in plan.entities]
    assert plan.entities and len(keys) == len(set(keys))
    assert {e.platform for e in plan.entities} <= PLATFORMS
    for entity in plan.entities:
        assert entity.writable == (entity.platform in ("number", "select", "switch"))
        if entity.platform == "number":
            assert entity.min_value is not None and entity.max_value is not None
        if entity.platform in ("select", "switch"):
            assert entity.options, entity.register_name


@pytest.mark.parametrize("name", NAMES)
def test_plan_summary_matches_the_golden_file(name: str) -> None:
    plan = plan_of(name)
    rows = [
        [e.platform, e.register_name, e.group_name, e.device, e.default_enabled, e.risk, e.unit]
        for e in plan.entities
    ]
    assert_golden(
        f"community_{name}",
        {
            "entities": sorted(map(str, rows)),
            "notes": sorted(f"{n.code}:{n.register}" for n in plan.notes),
        },
    )


def test_ncp_operation_mode_is_a_read_only_enum_with_visible_names_winning() -> None:
    """NCP: REG_OPERATIONMODE is read-only and value 2 exists twice (hidden and visible name)."""
    for name in ("ncp_1024", "ncp_1028"):
        plan = plan_of(name)
        [mode] = [e for e in plan.entities if e.register_name == "REG_OPERATIONMODE"]
        assert mode.platform == "sensor" and not mode.writable
        values = [v for v, _ in mode.options]
        assert len(values) == len(set(values))  # one name per value


def test_status_registers_become_flag_sensors() -> None:
    for name, register in (
        ("atec_dhp_aq", "COMP_STATUS_ATEC"),
        ("diplomat_duo_921", "COMP_STATUS"),
    ):
        flags = [e for e in plan_of(name).entities if e.register_name == register]
        assert flags and all(f.platform == "binary_sensor" for f in flags), (name, register)


def test_the_2024_itec_dump_differs_from_the_live_cloud() -> None:
    """The old dump still has registers the live account no longer returns."""
    live = {
        r["registerName"]
        for p in (Path(__file__).parent.parent / "fixtures" / "itec_profile_1005").glob(
            "group_*.json"
        )
        for r in json.loads(p.read_text())
    }
    old = {e.register_name for e in plan_of("itec_iq").entities}
    assert old - live  # registers only the older cloud returned
