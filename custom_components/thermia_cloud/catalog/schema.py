"""Voluptuous schema and typed model of ``catalog.yaml`` (see ``docs/CATALOG.md``)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import voluptuous as vol

CATALOG_VERSION = 1
MAIN_DEVICE = "main"


class Kind(StrEnum):
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    NUMBER = "number"
    SELECT = "select"
    SWITCH = "switch"
    SKIP = "skip"


class Risk(StrEnum):
    NONE = "none"
    HEATING = "heating"
    SERVICE = "service"


class Category(StrEnum):
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


_REGISTER = {
    vol.Required("kind"): vol.Coerce(Kind),
    vol.Optional("unit"): str,
    vol.Optional("device_class"): str,
    vol.Optional("state_class"): vol.In(["measurement", "total", "total_increasing"]),
    vol.Optional("icon"): str,
    vol.Optional("category"): vol.Coerce(Category),
    vol.Optional("default_enabled"): bool,
    vol.Optional("risk"): vol.Coerce(Risk),
    vol.Optional("translation_key"): str,
    vol.Optional("description_key"): str,
    vol.Optional("device"): str,
    # Allows a plain NAME key although the name occurs in several groups
    vol.Optional("shared"): bool,
    # The cloud only returns this register in some state (circuit mode, hot water on/off):
    # while it is absent its entity stays, unavailable, and no Repair issue is raised for it
    vol.Optional("state_dependent"): bool,
    # Status registers only: flags that are enabled even while the cloud hides them (the cloud
    # shows e.g. "hot water" only while hot water is on). Other hidden flags become disabled
    # diagnostic entities.
    vol.Optional("core_flags"): [str],
    # No entity when the installation status says the pump has no indoor-temperature sensor
    # (``hasIndoorTempSensor: false``): the register then only holds a stale leftover value
    vol.Optional("needs_indoor_sensor"): bool,
}

CATALOG_SCHEMA = vol.Schema(
    {
        vol.Required("version"): CATALOG_VERSION,
        vol.Required("devices"): {str: vol.Any(None, {vol.Optional("translation_key"): str})},
        vol.Optional("groups", default=dict): {
            str: {vol.Required("device"): str, vol.Optional("category"): vol.Coerce(Category)}
        },
        vol.Required("registers"): {str: _REGISTER},
    }
)


@dataclass(frozen=True, slots=True)
class CatalogDevice:
    key: str
    translation_key: str | None


@dataclass(frozen=True, slots=True)
class CatalogGroup:
    name: str
    device: str
    category: Category | None


@dataclass(frozen=True, slots=True)
class CatalogRegister:
    key: str  # "NAME" or "GROUP/NAME"
    kind: Kind
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    category: Category | None = None
    default_enabled: bool = False
    risk: Risk = Risk.NONE
    translation_key: str | None = None
    description_key: str | None = None
    device: str | None = None
    shared: bool = False
    state_dependent: bool = False
    core_flags: tuple[str, ...] = ()
    needs_indoor_sensor: bool = False

    @classmethod
    def from_validated(cls, key: str, data: dict[str, Any]) -> CatalogRegister:
        return cls(key=key, **{**data, "core_flags": tuple(data.get("core_flags", ()))})


@dataclass(frozen=True, slots=True)
class Catalog:
    devices: dict[str, CatalogDevice]
    groups: dict[str, CatalogGroup]
    registers: dict[str, CatalogRegister]

    def lookup(self, group: str, name: str) -> CatalogRegister | None:
        """``GROUP/NAME`` first, then plain ``NAME``."""
        return self.registers.get(f"{group}/{name}") or self.registers.get(name)

    def device_for(self, group: str, register: CatalogRegister | None = None) -> str:
        """Per-register ``device`` wins, then the group's device, then ``main``."""
        if register is not None and register.device:
            return register.device
        entry = self.groups.get(group)
        return entry.device if entry else MAIN_DEVICE

    def category_for(self, group: str, register: CatalogRegister | None) -> Category | None:
        if register is not None and register.category is not None:
            return register.category
        entry = self.groups.get(group)
        return entry.category if entry else None
