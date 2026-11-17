import importlib.util
import json
from pathlib import Path

from custom_components.thermia_cloud.catalog.flags import active_flags, flag_is_set, unnamed_bits
from custom_components.thermia_cloud.catalog.labels import (
    LabelResolver,
    humanize,
    load_bundled,
    pick_culture,
)
from custom_components.thermia_cloud.client.models import RegisterSpec, ValueName

FIXTURES = Path(__file__).parent.parent / "fixtures" / "itec_profile_1005"


def itec_status() -> RegisterSpec:
    raw = json.loads((FIXTURES / "group_REG_GROUP_OPERATIONAL_STATUS.json").read_text())
    return RegisterSpec.from_json(next(r for r in raw if r["registerName"] == "COMP_STATUS_ITEC"))


def test_flag_decoding_equality_vs_bitmask() -> None:
    assert flag_is_set(19, 16, equality=False) is True
    assert flag_is_set(19, 8, equality=False) is False
    assert flag_is_set(19, 16, equality=True) is False  # equality: only exact value
    assert flag_is_set(16, 16, equality=True) is True
    assert flag_is_set(None, 1, equality=False) is None


def test_itec_status_19_means_compressor_and_heating() -> None:
    state = active_flags(itec_status(), 19.0)
    assert state[1] is True and state[16] is True
    assert state[8] is False and state[32] is False
    assert 2 not in state  # radiator pump bit is hidden: no flag entity


def test_unnamed_bits_are_reported() -> None:
    names = [ValueName("A", 1, True, False, None), ValueName("B", 2, False, False, None)]
    assert unnamed_bits(19, names) == [16]  # 19 = 1 + 2 + 16; bit 16 has no name
    assert unnamed_bits(3, names) == []
    assert unnamed_bits(None, names) == []


BUNDLED = {
    "en-US": {"REG_X": "Curve [°C]", "REG_Y": "Only English", "REG_Z": "Zone [foo]"},
    "cs-CZ": {"REG_X": "Křivka [°C]", "REG_Z": "Zóna [foo]"},
    "cs-SK": {"REG_ONLY_SK": "Jen SK"},
}


def test_resolution_order() -> None:
    r = LabelResolver(
        "cs", BUNDLED, curated={"heating_curve": "Topná křivka"}, refreshed={"REG_X": "Nové [°C]"}
    )
    assert r.culture == "cs-CZ"
    assert r.label("REG_X", "heating_curve") == "Topná křivka"  # curated first
    assert r.label("REG_X") == "Nové"  # refreshed copy, known-unit bracket stripped
    assert r.label("REG_Y") == "Only English"  # falls back to en-US
    assert r.label("REG_ONLY_SK") == "Jen SK"  # same language, other culture
    assert r.label("REG_Z") == "Zóna [foo]"  # unknown bracket stays
    assert r.label("REG_OPER_TIME_IMM1") == "Oper time imm1"  # humanized key


def test_without_refresh_uses_bundled_and_literal_names_stay() -> None:
    r = LabelResolver("cs-CZ", BUNDLED)
    assert r.label("REG_X") == "Křivka"
    assert r.label("Comfort") == "Comfort"


def test_culture_selection() -> None:
    assert pick_culture("cs", BUNDLED) == "cs-CZ"
    assert pick_culture("de", BUNDLED) == "en-US"
    assert pick_culture("en-US", BUNDLED) == "en-US"
    assert LabelResolver("en", BUNDLED).culture == "en-US"


def test_humanize() -> None:
    assert humanize("COMP_VALUE_HOT_WATER") == "Hot water"
    assert humanize("REG_GROUP_HEATING_CURVE_CIRC1") == "Heating curve circ1"
    assert humanize("Away") == "Away"


def test_bundled_snapshots_load_when_present() -> None:
    bundled = load_bundled()
    assert all(isinstance(v, dict) for v in bundled.values())


def test_sync_script_filtering() -> None:
    spec = importlib.util.spec_from_file_location(
        "sync_localization",
        Path(__file__).parent.parent.parent / "scripts" / "sync_localization.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.filter_keys(
        {"REG_A": "a", "COMP_B": "b", "ALARM_C": "c", "UI_D": "d", "Comfort": "x"}, {"Comfort"}
    )
    assert out == {"COMP_B": "b", "Comfort": "x", "REG_A": "a"}
    assert "Comfort" in mod.fixture_value_names()


def test_real_snapshots_cover_the_itec_fixture() -> None:
    bundled = load_bundled()
    assert len(bundled) == 16
    names = {
        reg["registerName"]
        for path in FIXTURES.glob("group_*.json")
        for reg in json.loads(path.read_text())
    }
    resolver = LabelResolver("cs", bundled)
    assert resolver.label("REG_HEATING_HEAT_CURVE_MIN") == "Přívod – minimum"  # noqa: RUF001
    assert resolver.label("REG_HEATING_HEAT_CURVE") == "Křivka"  # bracket unit stripped
    missing = [n for n in sorted(names) if n not in bundled["cs-CZ"]]
    assert missing == []


def test_overrides_beat_the_snapshot_and_a_refreshed_copy() -> None:
    bundled = {"en-US": {"REG_A": "Actual RPM"}, "cs-CZ": {"REG_A": "Actual RPM", "REG_B": "Stará"}}
    overrides = {"cs-CZ": {"REG_A": "Aktuální otáčky"}}
    resolver = LabelResolver(
        "cs", bundled, refreshed={"REG_A": "Actual RPM", "REG_B": "Nová"}, overrides=overrides
    )
    assert resolver.label("REG_A") == "Aktuální otáčky"  # our correction wins everywhere
    assert resolver.label("REG_B") == "Nová"  # no override: the refreshed copy is used
    # other cultures are untouched
    assert LabelResolver("en", bundled, overrides=overrides).label("REG_A") == "Actual RPM"


def test_load_overrides_reads_the_directory(tmp_path: Path) -> None:
    from custom_components.thermia_cloud.catalog.labels import load_overrides

    (tmp_path / "cs-CZ.json").write_text('{"REG_A": "x"}', encoding="utf-8")
    assert load_overrides(tmp_path) == {"cs-CZ": {"REG_A": "x"}}
    assert load_overrides(tmp_path / "missing") == {}
