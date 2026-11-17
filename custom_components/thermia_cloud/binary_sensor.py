"""Binary sensors: one per visible status flag."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThermiaConfigEntry
from .catalog.flags import flag_is_set
from .entity import ThermiaEntity

PARALLEL_UPDATES = 0  # coordinator-based, no per-entity I/O


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaFlag(runtime.coordinator, plan, runtime.names[plan.key])
        for runtime in entry.runtime_data.installations
        for plan in runtime.plans
        if plan.platform == "binary_sensor"
    )


class ThermiaFlag(ThermiaEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        assert self.plan.flag_value is not None
        return flag_is_set(self._value, self.plan.flag_value, equality=self.plan.flag_equality)
