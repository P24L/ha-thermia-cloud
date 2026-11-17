"""Every curated name and device the catalog refers to must exist in both languages."""

import json
from pathlib import Path

import pytest

from custom_components.thermia_cloud.catalog.loader import load_catalog
from custom_components.thermia_cloud.catalog.schema import Kind

TRANSLATIONS = Path(__file__).parents[2] / "custom_components" / "thermia_cloud" / "translations"
LANGUAGES = ("en", "cs")


@pytest.mark.parametrize("language", LANGUAGES)
def test_catalog_translation_keys_exist(language: str) -> None:
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text())
    catalog = load_catalog()
    for register in catalog.registers.values():
        if register.translation_key:
            names = data["entity"][register.kind.value]
            assert register.translation_key in names, (register.key, register.kind)
    for device in catalog.devices.values():
        if device.translation_key:
            assert device.translation_key in data["device"], device.key


def _keys(node: object, prefix: str = "") -> set[str]:
    if isinstance(node, dict):
        return {k for key, v in node.items() for k in _keys(v, f"{prefix}/{key}")}
    return {prefix}


def _strings(node: object, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        return {
            k: v
            for key, child in node.items()
            for k, v in _strings(child, f"{prefix}/{key}").items()
        }
    return {prefix: str(node)}


ALL_FILES = sorted(TRANSLATIONS.glob("*.json"))


def test_every_curated_language_is_complete() -> None:
    assert {p.stem for p in ALL_FILES} >= {"en", "cs"}
    en = json.loads((TRANSLATIONS / "en.json").read_text())
    for path in ALL_FILES:
        assert _keys(json.loads(path.read_text())) == _keys(en), path.name


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.stem)
def test_placeholders_survive_translation(path: Path) -> None:
    import re

    pattern = re.compile(r"\{[a-z_]+\}")
    en = _strings(json.loads((TRANSLATIONS / "en.json").read_text()))
    for key, text in _strings(json.loads(path.read_text())).items():
        assert sorted(pattern.findall(text)) == sorted(pattern.findall(en[key])), (path.name, key)


OVERRIDES = sorted((Path(TRANSLATIONS).parent / "catalog" / "i18n" / "overrides").glob("*.json"))


@pytest.mark.parametrize("path", OVERRIDES, ids=lambda p: p.stem)
def test_label_overrides_are_sane(path: Path) -> None:
    import re

    base = Path(TRANSLATIONS).parent / "catalog" / "i18n"
    english = json.loads((base / "en-US.json").read_text())
    overrides = json.loads(path.read_text())
    bracket = re.compile(r"\[[^\]]+\]\s*$")
    for key, text in overrides.items():
        assert key in english, f"{key} is not a known Thermia key"
        assert (isinstance(text, str) and text.strip() and text != english[key]) or text == english[
            key
        ]
        # a unit bracket must be kept exactly as in the English text
        en_unit = bracket.search(english[key])
        if en_unit:
            assert text.rstrip().endswith(en_unit.group(0).strip()), (key, text)


def test_every_writable_catalog_entry_states_its_risk() -> None:
    import yaml

    raw = yaml.safe_load((Path(TRANSLATIONS).parent / "catalog" / "catalog.yaml").read_text())
    writable = {Kind.NUMBER.value, Kind.SELECT.value, Kind.SWITCH.value}
    missing = [k for k, v in raw["registers"].items() if v["kind"] in writable and "risk" not in v]
    assert missing == []
