"""Label resolution (``docs/CATALOG.md`` 5.2).

Order: curated name -> refreshed copy -> bundled snapshot of the chosen culture -> same language
in another culture -> en-US -> humanized key. Cloud labels lose a trailing ``[unit]`` bracket
only when the unit is a known one.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from pathlib import Path

from .units import strip_unit_bracket

I18N_DIR = Path(__file__).parent / "i18n"
FALLBACK_CULTURE = "en-US"
_KEYLIKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PREFIX = re.compile(r"^(REG_GROUP_|REG_VALUE_|COMP_VALUE_|REG_|COMP_)")


def load_bundled(directory: Path = I18N_DIR) -> dict[str, dict[str, str]]:
    """``{culture: {key: text}}`` from the bundled snapshots (``_meta.json`` is skipped)."""
    result: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        if not path.name.startswith("_"):
            result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return result


async def async_load_bundled(directory: Path = I18N_DIR) -> dict[str, dict[str, str]]:
    return await asyncio.to_thread(load_bundled, directory)


def humanize(key: str) -> str:
    """``REG_OPER_TIME_IMM1`` -> ``Oper time imm1``; texts that are not keys stay as they are."""
    if not _KEYLIKE.match(key):
        return key
    words = _PREFIX.sub("", key).replace("_", " ").lower()
    return words[:1].upper() + words[1:]


def pick_culture(language: str, available: Mapping[str, object]) -> str:
    """Culture for a language setting: an exact culture, a bare language (``cs``), or en-US."""
    if language in available:
        return language
    base = language.split("-")[0].split("_")[0].lower()
    for culture in sorted(available):
        if culture.split("-")[0].lower() == base:
            return culture
    return FALLBACK_CULTURE


class LabelResolver:
    def __init__(
        self,
        language: str,
        bundled: Mapping[str, Mapping[str, str]],
        *,
        curated: Mapping[str, str] | None = None,
        refreshed: Mapping[str, str] | None = None,
    ) -> None:
        self._culture = pick_culture(language, bundled)
        self._bundled = bundled
        self._curated = curated or {}
        self._refreshed = refreshed or {}
        base = self._culture.split("-")[0]
        self._same_language = [
            c for c in sorted(bundled) if c != self._culture and c.split("-")[0] == base
        ]

    @property
    def culture(self) -> str:
        return self._culture

    def label(self, key: str, translation_key: str | None = None) -> str:
        if translation_key and translation_key in self._curated:
            return self._curated[translation_key]
        sources = [self._refreshed, self._bundled.get(self._culture, {})]
        sources += [self._bundled[c] for c in self._same_language]
        sources.append(self._bundled.get(FALLBACK_CULTURE, {}))
        for source in sources:
            text = source.get(key)
            if text:
                return strip_unit_bracket(text)
        return humanize(key)
