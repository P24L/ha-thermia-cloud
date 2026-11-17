"""The one place where HA actions turn into register writes (policy, errors, read-back)."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .catalog.planner import effective_risk
from .catalog.schema import Risk
from .client.errors import RegisterValidationError, ThermiaError
from .const import CONF_READ_ONLY, DOMAIN
from .coordinator import ThermiaCoordinator


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


def ensure_writable(coordinator: ThermiaCoordinator) -> None:
    """Read-only mode blocks every write, entity or service."""
    entry = coordinator.config_entry
    if entry is not None and entry.options.get(CONF_READ_ONLY, False):
        raise _error("read_only_mode")


async def async_write_register(
    coordinator: ThermiaCoordinator, register_id: int, value: float
) -> None:
    """Validate and send one value, then watch for the read-back.

    Errors are raised to the caller (no silent failures, no debounce). Once the cloud has
    accepted the value this returns; a read-back that never matches is only logged.
    """
    ensure_writable(coordinator)
    spec = coordinator.spec(register_id)
    if spec is None:
        raise _error("unknown_register", register=str(register_id))
    entry = coordinator.config_entry
    if (
        entry is not None
        and effective_risk(spec, entry.runtime_data.catalog.lookup(spec.group_name, spec.name))
        is Risk.SERVICE
    ):
        raise _error("service_register", register=spec.name)
    api = coordinator.api
    try:
        sent = await api.write_register(coordinator.installation.id, spec, value)
    except RegisterValidationError as err:
        raise _error("invalid_value", detail=str(err)) from err
    except ThermiaError as err:
        raise _error("write_failed", detail=str(err)) from err
    coordinator.track_write(register_id, sent)
