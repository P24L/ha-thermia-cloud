"""Label resolution (``docs/CATALOG.md`` 5.2).

Order: curated name -> refreshed copy -> bundled snapshot of the chosen culture -> same language
in another culture -> curated English name -> en-US cloud text -> humanized key.
Cloud labels lose a trailing ``[unit]`` bracket only when the unit is a known one.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from .units import strip_unit_bracket

I18N_DIR = Path(__file__).parent / "i18n"
OVERRIDES_DIR = I18N_DIR / "overrides"
TRANSLATIONS_DIR = Path(__file__).parent.parent / "translations"
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


def load_overrides(directory: Path = OVERRIDES_DIR) -> dict[str, dict[str, str]]:
    """Our corrections of Thermia's texts, ``{culture: {key: text}}``.

    The bundled snapshots are verbatim copies of the cloud's texts and are never edited; where a
    text is missing (still English) or wrong we keep a correction here. It wins over both the
    snapshot and a refreshed copy.
    """
    if not directory.is_dir():
        return {}
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))
    }


async def async_load_overrides(directory: Path = OVERRIDES_DIR) -> dict[str, dict[str, str]]:
    return await asyncio.to_thread(load_overrides, directory)


async def async_load_bundled(directory: Path = I18N_DIR) -> dict[str, dict[str, str]]:
    return await asyncio.to_thread(load_bundled, directory)


def load_curated(language: str, directory: Path = TRANSLATIONS_DIR) -> dict[str, str]:
    """Our own names for entities and devices in one language: ``{translation_key: name}``.

    Read from the integration's ``translations/<language>.json`` (entity names plus device
    names). A language we have no file for gives an empty mapping.
    """
    path = directory / f"{language.split('-')[0].split('_')[0].lower()}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    for platform in data.get("entity", {}).values():
        names.update({key: value["name"] for key, value in platform.items()})
    names.update({key: value["name"] for key, value in data.get("device", {}).items()})
    return names


async def async_load_curated(language: str, directory: Path = TRANSLATIONS_DIR) -> dict[str, str]:
    return await asyncio.to_thread(load_curated, language, directory)


LABEL_PREFIXES = ("REG_", "COMP_")  # covers REG_GROUP_*, value names and component texts


def filter_label_keys(
    resources: Mapping[str, str], extra_keys: Iterable[str] = ()
) -> dict[str, str]:
    """Keep only register, group and value-name texts (alarm and UI texts are not copied)."""
    wanted = set(extra_keys)
    return {
        key: text
        for key, text in sorted(resources.items())
        if key.startswith(LABEL_PREFIXES) or key in wanted
    }


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
        curated_fallback: Mapping[str, str] | None = None,
        refreshed: Mapping[str, str] | None = None,
        overrides: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        overrides = overrides or {}
        self._culture = pick_culture(language, bundled)
        self._bundled = {c: {**texts, **overrides.get(c, {})} for c, texts in bundled.items()}
        self._curated = curated or {}
        self._curated_fallback = curated_fallback or {}  # English: used before en-US cloud text
        self._refreshed = {**(refreshed or {}), **overrides.get(self._culture, {})}
        base = self._culture.split("-")[0]
        # A language the cloud has no texts for resolves to en-US; for such users our own English
        # names are better than Thermia's terse English ones.
        self._english_fallback = language.split("-")[0].split("_")[0].lower() != "en" and (
            self._culture == FALLBACK_CULTURE
        )
        self._same_language = [
            c for c in sorted(bundled) if c != self._culture and c.split("-")[0] == base
        ]

    @property
    def culture(self) -> str:
        return self._culture

    def label(self, key: str, translation_key: str | None = None) -> str:
        for curated_key in (translation_key, key.lower()):  # register key, or the flag's cloud key
            if curated_key and curated_key in self._curated:
                return self._curated[curated_key]
        if self._english_fallback:
            sources: list[Mapping[str, str]] = []
            for curated_key in (translation_key, key.lower()):
                if curated_key and curated_key in self._curated_fallback:
                    return self._curated_fallback[curated_key]
        else:
            sources = [self._refreshed, self._bundled.get(self._culture, {})]
            sources += [self._bundled[c] for c in self._same_language]
        for source in sources:
            text = source.get(key)
            if text:
                return strip_unit_bracket(text)
        for curated_key in (translation_key, key.lower()):
            if curated_key and curated_key in self._curated_fallback:
                return self._curated_fallback[curated_key]
        text = self._bundled.get(FALLBACK_CULTURE, {}).get(key)
        if text:
            return strip_unit_bracket(text)
        return humanize(key)
