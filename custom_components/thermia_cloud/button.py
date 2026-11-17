"""Buttons on the installation device: refresh names, rediscover registers (diagnostic)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InstallationRuntime, ThermiaConfigEntry, async_rediscover, async_refresh_labels
from .client.errors import ThermiaError
from .const import DOMAIN
from .entity import device_identifier

BUTTONS = ("refresh_names", "rediscover")

PARALLEL_UPDATES = 1  # writes are serialized


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermiaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        ThermiaButton(entry, runtime, key)
        for runtime in entry.runtime_data.installations
        for key in BUTTONS
    )


class ThermiaButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ThermiaConfigEntry, runtime: InstallationRuntime, key: str) -> None:
        self._entry = entry
        self._runtime = runtime
        self._key = key
        self._attr_unique_id = f"{runtime.installation.id}_{key}"
        self._attr_translation_key = key
        self._attr_name = entry.runtime_data.labels.label(key, key)
        self._attr_device_info = DeviceInfo(
            identifiers={device_identifier(runtime.installation.id, "main")}
        )

    async def async_press(self) -> None:
        try:
            if self._key == "refresh_names":
                await async_refresh_labels(self.hass, self._entry)
            else:
                await async_rediscover(self.hass, self._entry, self._runtime.installation.id)
        except ThermiaError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"detail": str(err)},
            ) from err
