"""``thermia_cloud.set_register``: write any register by name, even one without an entity.

Same policy as the entities: read-only mode, installer-level (``service``) registers refused,
validation against the cloud's limits / visible values. Returns once the cloud accepted the
value; it does not wait for the read-back.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import ThermiaCoordinator
from .writer import async_write_register

SERVICE_SET_REGISTER = "set_register"
SET_REGISTER_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("group"): cv.string,
        vol.Required("register"): vol.Any(cv.positive_int, cv.string),
        vol.Required("value"): vol.Coerce(float),
    }
)


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> ThermiaCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            installation_id = int(identifier.split("_")[0])
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
                    continue
                for runtime in entry.runtime_data.installations:
                    if runtime.installation.id == installation_id:
                        return runtime.coordinator
    raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_installation")


async def _async_set_register(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _coordinator_for_device(hass, call.data["device_id"])
    wanted = str(call.data["register"])
    group = call.data["group"]
    spec = next(
        (
            s
            for s in coordinator.discovery.specs
            if s.group_name == group and wanted in (s.name, str(s.register_index))
        ),
        None,
    )
    if spec is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="unknown_register",
            translation_placeholders={"register": f"{group}/{wanted}"},
        )
    await async_write_register(coordinator, spec.register_id, call.data["value"])


def async_register_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN, SERVICE_SET_REGISTER, _async_set_register, schema=SET_REGISTER_SCHEMA
    )
