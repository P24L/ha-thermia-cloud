"""Base entity shared by all platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .catalog.planner import EntityPlan
from .const import DOMAIN
from .coordinator import ThermiaCoordinator


def device_identifier(installation_id: int, device: str) -> tuple[str, str]:
    """Identifier of the installation device (``main``) or one of its child devices."""
    return (DOMAIN, str(installation_id) if device == "main" else f"{installation_id}_{device}")


class ThermiaEntity(CoordinatorEntity[ThermiaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ThermiaCoordinator, plan: EntityPlan, name: str | None) -> None:
        super().__init__(coordinator)
        self.plan = plan
        self._attr_unique_id = f"{coordinator.installation.id}_{plan.key}"
        if plan.translation_key:
            self._attr_translation_key = plan.translation_key
        else:
            self._attr_name = name
        self._attr_entity_registry_enabled_default = plan.default_enabled
        if plan.entity_category:
            self._attr_entity_category = EntityCategory(plan.entity_category)
        if plan.icon:
            self._attr_icon = plan.icon
        self._attr_device_info = DeviceInfo(
            identifiers={device_identifier(coordinator.installation.id, plan.device)}
        )

    @property
    def _value(self) -> Any:
        data = self.coordinator.data
        entry = data.values.get(self.plan.register_id) if data else None
        return entry.value if entry else None

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and self.plan.register_id in data.values
            and self.plan.register_id not in data.inactive
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        entry = data.values.get(self.plan.register_id) if data else None
        attrs: dict[str, Any] = {}
        if entry and entry.timestamp:
            attrs["register_timestamp"] = entry.timestamp.isoformat()
        if self.plan.stale:
            attrs["stale"] = True
        return attrs
