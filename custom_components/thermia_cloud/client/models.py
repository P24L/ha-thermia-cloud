"""Immutable data classes for what the cloud returns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse a register ``timeStamp``. The cloud sends it without a zone (naive)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Installation:
    id: int
    name: str
    model: str
    is_online: bool
    firmware_version: str | None
    last_online: str | None
    # Private: never shown in repr/logs.
    mac_address: str | None = field(default=None, repr=False)

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Installation:
        return cls(
            id=int(d["id"]),
            name=str(d.get("name") or ""),
            model=str(d.get("model") or ""),
            is_online=bool(d.get("isOnline")),
            firmware_version=d.get("firmwareVersion"),
            last_online=d.get("lastOnline"),
            mac_address=d.get("macAddress"),
        )


@dataclass(frozen=True, slots=True)
class InstallationDetail:
    id: int
    profile_id: int
    time_zone_id: str | None

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> InstallationDetail:
        return cls(
            id=int(d["id"]),
            profile_id=int(d["installationProfileId"]),
            time_zone_id=d.get("timeZoneId"),
        )


@dataclass(frozen=True, slots=True)
class Group:
    id: int
    name: str
    parent_id: int | None
    visibility: int | None
    description: str | None

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Group:
        return cls(
            id=int(d["id"]),
            name=str(d["name"]),
            parent_id=d.get("parentId"),
            visibility=d.get("visibility"),
            description=d.get("description"),
        )


@dataclass(frozen=True, slots=True)
class ValueName:
    name: str
    value: int
    visible: bool
    is_readonly: bool
    confirmation: str | None

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> ValueName:
        return cls(
            name=str(d["name"]),
            value=int(d["value"]),
            visible=bool(d.get("visible", True)),
            is_readonly=bool(d.get("isReadonly", False)),
            confirmation=d.get("confirmation"),
        )


@dataclass(frozen=True, slots=True)
class RegisterSpec:
    """Static description of a register (what the cloud says about it)."""

    register_id: int  # write id (registerSpecificationId)
    register_index: int  # stable index; the history endpoint calls it registerId
    name: str
    group_name: str
    group_id: int
    presentation: str
    modifier: int
    unit: str | None
    min_value: float | None
    max_value: float | None
    step: float | None
    is_read_only: bool
    is_invisible: bool
    true_text: str | None
    false_text: str | None
    value_names: tuple[ValueName, ...]

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> RegisterSpec:
        return cls(
            register_id=int(d["registerId"]),
            register_index=int(d["registerIndex"]),
            name=str(d["registerName"]),
            group_name=str(d["groupName"]),
            group_id=int(d["groupId"]),
            presentation=str(d.get("presentation") or ""),
            modifier=int(d.get("modifier") or 0),
            unit=d.get("unit"),
            min_value=d.get("minValue"),
            max_value=d.get("maxValue"),
            step=d.get("step"),
            is_read_only=bool(d.get("isReadOnly", True)),
            is_invisible=bool(d.get("isInvisible", False)),
            true_text=d.get("trueText"),
            false_text=d.get("falseText"),
            value_names=tuple(ValueName.from_json(v) for v in d.get("valueNames") or ()),
        )


@dataclass(frozen=True, slots=True)
class RegisterValue:
    register_id: int
    value: float | None
    string_value: str | None
    timestamp: datetime | None  # naive, see parse_timestamp

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> RegisterValue:
        return cls(
            register_id=int(d["registerId"]),
            value=d.get("registerValue"),
            string_value=d.get("stringRegisterValue"),
            timestamp=parse_timestamp(d.get("timeStamp")),
        )


@dataclass(frozen=True, slots=True)
class HistoryRegister:
    """Entry of the history list; carries the visibility conditions."""

    register_index: int  # the endpoint's ``registerId``
    name: str
    visibility_condition: str | None
    exclusive_visibility_condition: str | None
    disabled_register_value: float | None

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> HistoryRegister:
        return cls(
            register_index=int(d["registerId"]),
            name=str(d["registerName"]),
            visibility_condition=d.get("registerVisibilityCondition"),
            exclusive_visibility_condition=d.get("exclusiveVisibilityCondition"),
            disabled_register_value=d.get("disabledRegisterValue"),
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Values of one installation at one poll, keyed by ``register_id``."""

    values: Mapping[int, RegisterValue]
