"""Status-flag decoding.

Working rule (``docs/ARCHITECTURE.md`` 4.1, roadmap P0.7 still open for other families):
``StatusFlags`` presentation -> equality, every other flag presentation -> bitmask.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..client.models import RegisterSpec, ValueName


def flag_is_set(value: float | None, flag: int, *, equality: bool) -> bool | None:
    """State of one flag; ``None`` when the register has no value."""
    if value is None:
        return None
    raw = int(value)
    return raw == flag if equality else raw & flag == flag


def unnamed_bits(value: float | None, names: Iterable[ValueName]) -> list[int]:
    """Set bits that no value name (visible or hidden) describes, for a diagnostic attribute."""
    if value is None:
        return []
    named = 0
    for name in names:
        named |= name.value
    raw = int(value)
    return [1 << i for i in range(raw.bit_length()) if raw & (1 << i) and not named & (1 << i)]


def active_flags(spec: RegisterSpec, value: float | None) -> dict[int, bool]:
    """``{flag value: is set}`` for the visible flags of a status register."""
    equality = spec.presentation == "StatusFlags"
    result: dict[int, bool] = {}
    for name in spec.value_names:
        if name.visible and name.value not in result:
            state = flag_is_set(value, name.value, equality=equality)
            if state is not None:
                result[name.value] = state
    return result
