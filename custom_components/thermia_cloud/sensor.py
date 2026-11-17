"""Sensors: measured values, operating hours, timestamps, read-only enumerations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThermiaConfigEntry
from .catalog.planner import option_key
from .entity import ThermiaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaSensor(runtime.coordinator, plan, runtime.names[plan.key])
        for runtime in entry.runtime_data.installations
        for plan in runtime.plans
        if plan.platform == "sensor"
    )


class ThermiaSensor(ThermiaEntity, SensorEntity):
    def __init__(self, coordinator, plan, name) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, plan, name)
        self._attr_native_unit_of_measurement = plan.unit
        self._attr_device_class = plan.device_class
        self._attr_state_class = plan.state_class
        if plan.display_precision is not None:
            self._attr_suggested_display_precision = plan.display_precision
        if plan.options:
            self._attr_options = [option_key(name) for _, name in plan.options]

    @property
    def native_value(self) -> Any:
        value = self._value
        if value is None:
            return None
        if self.plan.device_class == "timestamp":
            return datetime.fromtimestamp(value, UTC)
        if self.plan.options:
            names = {v: option_key(n) for v, n in self.plan.options}
            return names.get(int(value))
        return value
