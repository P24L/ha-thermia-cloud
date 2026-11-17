"""Validation of a register write. Pure: never talks to the cloud, never clamps.

Numbers are checked against the cloud's ``min/max/step``; enumerations against the **visible**
``valueNames`` (``min/max`` can be ``null`` or wrong there, ``docs/API-NOTES.md`` section 10).
"""

from __future__ import annotations

import math

from .errors import RegisterWriteError
from .models import RegisterSpec

_STEP_TOLERANCE = 1e-6


def validate_write(spec: RegisterSpec, value: float) -> float | int:
    """Return the value to send, or raise :class:`RegisterWriteError`."""
    if spec.is_read_only:
        raise RegisterWriteError(f"{spec.name} is read-only")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise RegisterWriteError(f"{value!r} is not a number")

    if spec.presentation == "Enumeration":
        allowed = {v.value for v in spec.value_names if v.visible and not v.is_readonly}
        if value not in allowed:
            raise RegisterWriteError(f"{value} is not one of {sorted(allowed)} for {spec.name}")
    elif spec.presentation in ("Integer", "Slider"):
        if spec.min_value is None or spec.max_value is None:
            raise RegisterWriteError(f"{spec.name} has no limits to validate against")
        if not spec.min_value <= value <= spec.max_value:
            raise RegisterWriteError(
                f"{value} is outside {spec.min_value}..{spec.max_value} for {spec.name}"
            )
        if spec.step:
            steps = (value - spec.min_value) / spec.step
            if abs(steps - round(steps)) > _STEP_TOLERANCE:
                raise RegisterWriteError(
                    f"{value} is not {spec.min_value} plus a multiple of {spec.step} "
                    f"for {spec.name}"
                )
    else:
        raise RegisterWriteError(f"{spec.name} ({spec.presentation}) cannot be written")

    return int(value) if float(value).is_integer() else float(value)
