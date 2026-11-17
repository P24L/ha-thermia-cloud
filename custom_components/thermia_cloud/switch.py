"""Switches: writable two-value enumerations (0 = off, 1 = on)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThermiaConfigEntry
from .entity import ThermiaEntity
from .writer import async_write_register


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaSwitch(runtime.coordinator, plan, runtime.names[plan.key])
        for runtime in entry.runtime_data.installations
        for plan in runtime.plans
        if plan.platform == "switch"
    )


class ThermiaSwitch(ThermiaEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        value = self._value
        return None if value is None else int(value) == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_write_register(self.coordinator, self.plan.register_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_write_register(self.coordinator, self.plan.register_id, 0)
