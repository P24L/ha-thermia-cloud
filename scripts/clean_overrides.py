"""Normalize label overrides after (machine-assisted) editing.

    python scripts/clean_overrides.py

For every ``catalog/i18n/overrides/<culture>.json``: drop keys Thermia does not know, drop entries
identical to the snapshot, and restore the English unit bracket (``[°C]``, ``[h]``) where the
override translated or removed it, because units are always taken from the English text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

I18N = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "thermia_cloud"
    / "catalog"
    / "i18n"
)
BRACKET = re.compile(r"\s*\[[^\]]+\]\s*$")


def clean(
    overrides: dict[str, str], english: dict[str, str], snapshot: dict[str, str]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, text in sorted(overrides.items()):
        if key not in english or not isinstance(text, str) or not text.strip():
            continue
        unit = BRACKET.search(english[key])
        if unit and not text.rstrip().endswith(unit.group(0).strip()):
            text = BRACKET.sub("", text) + " " + unit.group(0).strip()
        text = text.strip()
        if text != snapshot.get(key):
            result[key] = text
    return result


def main() -> None:
    english = json.loads((I18N / "en-US.json").read_text(encoding="utf-8"))
    for path in sorted((I18N / "overrides").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        snapshot = json.loads((I18N / path.name).read_text(encoding="utf-8"))
        cleaned = clean(raw, english, snapshot)
        path.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"{path.stem}: {len(raw)} -> {len(cleaned)}")


if __name__ == "__main__":
    main()
