"""Selects: writable enumerations; options are the cloud's *visible* values."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThermiaConfigEntry
from .catalog.planner import option_key
from .entity import ThermiaEntity
from .writer import async_write_register

PARALLEL_UPDATES = 1  # writes are serialized


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaSelect(runtime.coordinator, plan, runtime.names[plan.key])
        for runtime in entry.runtime_data.installations
        for plan in runtime.plans
        if plan.platform == "select"
    )


class ThermiaSelect(ThermiaEntity, SelectEntity):
    def __init__(self, coordinator, plan, name) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, plan, name)
        self._by_option = {option_key(n): v for v, n in plan.options}
        self._by_value = {v: option_key(n) for v, n in plan.options}
        self._attr_options = list(self._by_option)

    @property
    def current_option(self) -> str | None:
        value = self._value
        return None if value is None else self._by_value.get(int(value))

    async def async_select_option(self, option: str) -> None:
        await async_write_register(self.coordinator, self.plan.register_id, self._by_option[option])
