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


def test_both_languages_have_the_same_keys() -> None:
    def keys(node: object, prefix: str = "") -> set[str]:
        if isinstance(node, dict):
            return {k for key, v in node.items() for k in keys(v, f"{prefix}/{key}")}
        return {prefix}

    en, cs = (json.loads((TRANSLATIONS / f"{lang}.json").read_text()) for lang in LANGUAGES)
    assert keys(en) == keys(cs)


def test_every_writable_catalog_entry_states_its_risk() -> None:
    import yaml

    raw = yaml.safe_load((Path(TRANSLATIONS).parent / "catalog" / "catalog.yaml").read_text())
    writable = {Kind.NUMBER.value, Kind.SELECT.value, Kind.SWITCH.value}
    missing = [k for k, v in raw["registers"].items() if v["kind"] in writable and "risk" not in v]
    assert missing == []
