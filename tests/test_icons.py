"""icons.json: every icon is a real mdi icon and every key names a known entity translation."""

import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "custom_components" / "thermia_cloud"
ICONS = json.loads((PACKAGE / "icons.json").read_text())["entity"]
EN = json.loads((PACKAGE / "translations" / "en.json").read_text())["entity"]


def _mdi_names() -> set[str]:
    hass_frontend = pytest.importorskip("hass_frontend")

    path = Path(hass_frontend.__file__).parent / "static" / "mdi" / "iconList.json"
    return {i["name"] if isinstance(i, dict) else i for i in json.loads(path.read_text())}


def test_every_icon_is_a_known_mdi_icon() -> None:
    known = _mdi_names()
    used = {
        icon
        for platform in ICONS.values()
        for entry in platform.values()
        for icon in [entry.get("default"), *entry.get("state", {}).values()]
        if icon
    }
    assert {i for i in used if i.removeprefix("mdi:") not in known} == set()


def test_every_icon_key_has_an_entity_name_translation() -> None:
    missing = [
        f"{platform}.{key}"
        for platform, items in ICONS.items()
        for key in items
        if key not in EN.get(platform, {})
    ]
    # entities added later with their own names (alarms, connectivity) are named in the same file
    assert missing == [], missing
