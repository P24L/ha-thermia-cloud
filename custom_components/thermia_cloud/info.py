"""Entities about the installation itself: connection, last contact, alarms.

They come from the installation status (``installationsInfo``), which the coordinator re-reads
every few minutes, not from registers. ``last_contact`` is also the practical answer to "is the
data fresh?": register timestamps only move when a value changes (the outdoor temperature can
stand still for a day), but the gateway's last contact keeps moving.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import InstallationRuntime, ThermiaConfigEntry
from .client.models import Installation
from .coordinator import ThermiaCoordinator
from .entity import device_identifier


@dataclass(frozen=True, slots=True)
class InfoSpec:
    key: str
    value: Callable[[Installation], Any]
    category: EntityCategory | None = None
    device_class: str | None = None
    state_class: str | None = None


LAST_CONTACT = InfoSpec(
    "last_contact",
    lambda i: i.last_online_utc,
    EntityCategory.DIAGNOSTIC,
    SensorDeviceClass.TIMESTAMP,
)
ALARM_COUNT = InfoSpec(
    "alarm_count",
    lambda i: i.active_alarms,
    EntityCategory.DIAGNOSTIC,
    state_class=SensorStateClass.MEASUREMENT,
)
CONNECTED = InfoSpec(
    "connected",
    lambda i: i.is_online,
    EntityCategory.DIAGNOSTIC,
    BinarySensorDeviceClass.CONNECTIVITY,
)
ACTIVE_ALARM = InfoSpec(
    "active_alarm",
    lambda i: None if i.active_alarms is None else i.active_alarms > 0,
    None,
    BinarySensorDeviceClass.PROBLEM,
)


class _InfoEntity(CoordinatorEntity[ThermiaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, entry: ThermiaConfigEntry, runtime: InstallationRuntime, spec: InfoSpec):
        super().__init__(runtime.coordinator)
        self._spec = spec
        self._attr_unique_id = f"{runtime.installation.id}_{spec.key}"
        self._attr_translation_key = spec.key
        self._attr_name = entry.runtime_data.labels.label(spec.key, spec.key)
        self._attr_entity_category = spec.category
        self._attr_device_class = spec.device_class
        self._attr_device_info = DeviceInfo(
            identifiers={device_identifier(runtime.installation.id, "main")}
        )

    @property
    def _installation(self) -> Installation:
        data = self.coordinator.data
        return data.installation if data and data.installation else self.coordinator.installation


class InfoSensor(_InfoEntity, SensorEntity):
    def __init__(self, entry: ThermiaConfigEntry, runtime: InstallationRuntime, spec: InfoSpec):
        super().__init__(entry, runtime, spec)
        self._attr_state_class = spec.state_class

    @property
    def native_value(self) -> datetime | int | None:
        value: datetime | int | None = self._spec.value(self._installation)
        return value


class InfoBinarySensor(_InfoEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        value: bool | None = self._spec.value(self._installation)
        return value
