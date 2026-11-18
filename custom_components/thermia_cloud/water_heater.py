"""A water heater entity for the hot water: the standard Home Assistant card and voice control.

Built from the generic registers (the hot water switch, the optional hot water mode and the hot
water temperature); the switch, select and sensor entities stay. There is no setpoint: the heat
pump decides the temperature, the entity offers on/off and the comfort / economy / away modes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.water_heater import (
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import InstallationRuntime, ThermiaConfigEntry
from .catalog.planner import EntityPlan, option_key
from .coordinator import ThermiaCoordinator
from .entity import device_identifier, register_value
from .writer import async_write_register

PARALLEL_UPDATES = 1
# the hot water mode register only exists while hot water is on: wait for it after switching on
MODE_WAIT_STEPS = 6
MODE_WAIT_SECONDS = 2


def _find(plans: tuple[EntityPlan, ...], **match: Any) -> EntityPlan | None:
    return next((p for p in plans if all(getattr(p, k) == v for k, v in match.items())), None)


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities = []
    for runtime in entry.runtime_data.installations:
        status = _find(runtime.plans, platform="switch", translation_key="hot_water")
        if status is None:
            continue
        mode = _find(
            runtime.plans,
            platform="select",
            translation_key="hot_water_mode",
        )
        temperature = _find(runtime.plans, translation_key="hot_water_temperature")
        entities.append(ThermiaWaterHeater(entry, runtime, status, mode, temperature))
    async_add_entities(entities)


class ThermiaWaterHeater(CoordinatorEntity[ThermiaCoordinator], WaterHeaterEntity):
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        entry: ThermiaConfigEntry,
        runtime: InstallationRuntime,
        status: EntityPlan,
        mode: EntityPlan | None,
        temperature: EntityPlan | None,
    ) -> None:
        super().__init__(runtime.coordinator)
        self._status = status
        self._mode = mode
        self._temperature = temperature
        self._attr_unique_id = f"{runtime.installation.id}_water_heater"
        self._attr_translation_key = "hot_water"
        self._attr_name = entry.runtime_data.labels.label("hot_water", "hot_water")
        self._by_option = {option_key(n): v for v, n in mode.options} if mode else {}
        self._by_value = {v: k for k, v in self._by_option.items()}
        self._attr_operation_list = [STATE_OFF, *self._by_option]
        self._attr_supported_features = WaterHeaterEntityFeature.ON_OFF | (
            WaterHeaterEntityFeature.OPERATION_MODE if mode else WaterHeaterEntityFeature(0)
        )
        self._attr_device_info = DeviceInfo(
            identifiers={device_identifier(runtime.installation.id, "main")}
        )

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data is not None and self._status.register_id in data.values

    @property
    def current_temperature(self) -> float | None:
        if self._temperature is None:
            return None
        value = register_value(self.coordinator, self._temperature.register_id)
        return None if value is None else float(value)

    @property
    def current_operation(self) -> str | None:
        status = register_value(self.coordinator, self._status.register_id)
        if status is None:
            return None
        if int(status) == 0:
            return STATE_OFF
        if self._mode is None:
            return None
        mode = register_value(self.coordinator, self._mode.register_id)
        return None if mode is None else self._by_value.get(int(mode))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_write_register(self.coordinator, self._status.register_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_write_register(self.coordinator, self._status.register_id, 0)

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_OFF:
            await self.async_turn_off()
            return
        if self._mode is None or operation_mode not in self._by_option:
            return
        status = register_value(self.coordinator, self._status.register_id)
        if status is None or int(status) == 0:
            await self.async_turn_on()
            await self._wait_for_mode_register()
        await async_write_register(
            self.coordinator, self._mode.register_id, self._by_option[operation_mode]
        )

    async def _wait_for_mode_register(self) -> None:
        """Switching hot water on makes the mode register appear a moment later."""
        assert self._mode is not None
        for _ in range(MODE_WAIT_STEPS):
            await self.coordinator.async_refresh()
            data = self.coordinator.data
            if data is not None and self._mode.register_id in data.values:
                return
            await asyncio.sleep(MODE_WAIT_SECONDS)
