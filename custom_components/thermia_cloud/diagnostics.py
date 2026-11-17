"""Redacted diagnostics: enough to add a new model, nothing that identifies the user."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ThermiaConfigEntry
from .const import CONF_INSTALLATIONS, CONF_PASSWORD, CONF_REFRESH_TOKEN, CONF_USERNAME

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_INSTALLATIONS,  # installation ids are private
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThermiaConfigEntry
) -> dict[str, Any]:
    installations = []
    for number, runtime in enumerate(entry.runtime_data.installations, 1):
        data = runtime.coordinator.data
        discovery = runtime.coordinator.discovery
        specs = {s.register_id: s for s in discovery.all_specs}
        installations.append(
            {
                # no installation id, name or MAC: the position stands in for them
                "installation": number,
                "model": runtime.installation.model,
                "firmware": runtime.installation.firmware_version,
                "online": runtime.installation.is_online,
                "profile_id": discovery.profile_id,
                "discovery_age_s": round(discovery.age_seconds()),
                "groups": list(discovery.groups),
                "specs": [asdict(s) for s in discovery.all_specs],
                "remembered": sorted(r.spec.name for r in discovery.remembered),
                "history": [asdict(h) for h in discovery.history],
                "values": {
                    specs[i].name + f"@{specs[i].group_name}": {
                        "value": v.value,
                        "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                    }
                    for i, v in (data.values.items() if data else ())
                    if i in specs
                },
                "inactive": sorted(
                    specs[i].name for i in (data.inactive if data else ()) if i in specs
                ),
                "entities": [
                    {
                        "platform": p.platform,
                        "key": p.key,
                        "register": p.register_name,
                        "group": p.group_name,
                        "device": p.device,
                        "default_enabled": p.default_enabled,
                        "stale": p.stale,
                        "risk": p.risk,
                        "runtime_condition": p.runtime_condition,
                    }
                    for p in runtime.plans
                ],
                "notes": [asdict(n) for n in runtime.notes],
            }
        )
    return {
        "entry": async_redact_data(
            {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "title": entry.title,
                "unique_id": entry.unique_id,
            },
            TO_REDACT,
        ),
        "installations": installations,
    }
