"""Unit resolution: catalog -> modifier -> en-US label bracket -> none."""

from __future__ import annotations

import re

# ``modifier`` hints seen on profile 1005 (API-NOTES section 4). 0 says nothing.
MODIFIER_UNITS: dict[int, str] = {8: "°C", 12: "°C", 1: "°C", 16: "h"}
TEMPERATURE_MODIFIERS = frozenset({8, 12, 1})
HOURS_MODIFIER = 16

# Units are only ever parsed from the *English* label through this fixed table.
KNOWN_UNITS = (
    "°C", "°F", "K", "%", "h", "d", "min", "s", "W", "kW", "kWh", "bar", "l/min", "m³/h",
    "V", "A", "Hz", "rpm",
)  # fmt: skip
_BRACKET = re.compile(r"\[([^\[\]]+)\]\s*$")


def bracket_unit(label: str | None) -> str | None:
    """``"Curve [°C]"`` -> ``"°C"``; unknown bracket content gives ``None``."""
    if not label:
        return None
    match = _BRACKET.search(label)
    if match and match.group(1).strip() in KNOWN_UNITS:
        return match.group(1).strip()
    return None


def strip_unit_bracket(label: str) -> str:
    """Remove a trailing bracket only when its content is a known unit."""
    if bracket_unit(label):
        return _BRACKET.sub("", label).rstrip()
    return label


def resolve_unit(catalog_unit: str | None, modifier: int, en_label: str | None) -> str | None:
    return catalog_unit or MODIFIER_UNITS.get(modifier) or bracket_unit(en_label)
