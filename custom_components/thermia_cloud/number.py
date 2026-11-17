"""Numbers: writable sliders/integers with the cloud's own limits."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ThermiaConfigEntry
from .entity import ThermiaEntity
from .writer import async_write_register


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaNumber(runtime.coordinator, plan, runtime.names[plan.key])
        for runtime in entry.runtime_data.installations
        for plan in runtime.plans
        if plan.platform == "number"
    )


class ThermiaNumber(ThermiaEntity, NumberEntity):
    def __init__(self, coordinator, plan, name) -> None:  # type: ignore[no-untyped-def]
        super().__init__(coordinator, plan, name)
        assert plan.min_value is not None and plan.max_value is not None
        self._attr_native_min_value = plan.min_value
        self._attr_native_max_value = plan.max_value
        self._attr_native_step = plan.step or 1.0
        self._attr_native_unit_of_measurement = plan.unit
        self._attr_device_class = plan.device_class
        self._attr_mode = NumberMode.SLIDER if plan.number_mode == "slider" else NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        await async_write_register(self.coordinator, self.plan.register_id, value)
