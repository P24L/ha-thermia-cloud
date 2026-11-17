"""Load and validate ``catalog.yaml``. Sync core, async wrapper for the event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

from .schema import (
    CATALOG_SCHEMA,
    MAIN_DEVICE,
    Catalog,
    CatalogDevice,
    CatalogGroup,
    CatalogRegister,
)

DEFAULT_PATH = Path(__file__).parent / "catalog.yaml"


class CatalogError(ValueError):
    """The catalog file is invalid."""


def parse_catalog(text: str) -> Catalog:
    try:
        data: dict[str, Any] = CATALOG_SCHEMA(yaml.safe_load(text))
    except (vol.Invalid, yaml.YAMLError) as err:
        raise CatalogError(str(err)) from err

    devices = {
        key: CatalogDevice(key, (value or {}).get("translation_key"))
        for key, value in data["devices"].items()
    }
    devices.setdefault(MAIN_DEVICE, CatalogDevice(MAIN_DEVICE, None))
    groups = {
        name: CatalogGroup(name, value["device"], value.get("category"))
        for name, value in data["groups"].items()
    }
    registers = {
        key: CatalogRegister.from_validated(key, value) for key, value in data["registers"].items()
    }

    for group in groups.values():
        if group.device not in devices:
            raise CatalogError(f"group {group.name}: unknown device {group.device!r}")
    for register in registers.values():
        if register.device is not None and register.device not in devices:
            raise CatalogError(f"register {register.key}: unknown device {register.device!r}")
    return Catalog(devices, groups, registers)


def load_catalog(path: Path = DEFAULT_PATH) -> Catalog:
    return parse_catalog(path.read_text(encoding="utf-8"))


async def async_load_catalog(path: Path = DEFAULT_PATH) -> Catalog:
    """Read the file in a worker thread: no blocking I/O in the event loop."""
    return await asyncio.to_thread(load_catalog, path)


def ambiguous_plain_keys(
    catalog: Catalog, registers: Iterable[tuple[str, str]] | Mapping[str, set[str]]
) -> list[str]:
    """Plain ``NAME`` keys that match a name living in several groups.

    ``registers`` is an iterable of ``(group, name)`` pairs (e.g. from fixtures). Such a key
    could silently apply to the wrong register, so it must be written ``GROUP/NAME``, unless
    the entry is explicitly ``shared`` (e.g. the heating curve of the main and circuit-1 groups).
    """
    pairs = (
        [(g, n) for n, groups in registers.items() for g in groups]
        if isinstance(registers, Mapping)
        else list(registers)
    )
    groups_by_name: dict[str, set[str]] = {}
    for group, name in pairs:
        groups_by_name.setdefault(name, set()).add(group)
    return sorted(
        key
        for key, entry in catalog.registers.items()
        if "/" not in key and not entry.shared and len(groups_by_name.get(key, ())) > 1
    )
