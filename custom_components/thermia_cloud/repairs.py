"""Repair issues. None of them is fixable from inside Home Assistant; they explain what to do."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _create(
    hass: HomeAssistant, issue_id: str, key: str, severity: ir.IssueSeverity, **placeholders: str
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=severity,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def sync_policy_acceptance(hass: HomeAssistant, entry_id: str, required: bool) -> None:
    """Thermia wants the user to accept new terms in the web app before login works again."""
    issue_id = f"policy_acceptance_required_{entry_id}"
    if required:
        _create(hass, issue_id, "policy_acceptance_required", ir.IssueSeverity.ERROR)
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def sync_discovery_empty(
    hass: HomeAssistant, entry_id: str, installation_id: int, empty: bool
) -> None:
    """The cloud returned no registers at all for an installation."""
    issue_id = f"discovery_empty_{entry_id}_{installation_id}"
    if empty:
        _create(hass, issue_id, "discovery_empty", ir.IssueSeverity.WARNING)
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def sync_vanished(
    hass: HomeAssistant, entry_id: str, installation_id: int, long_missing: list[str]
) -> None:
    """Registers that have been missing for a long time (the entities stay ``unavailable``)."""
    issue_id = f"register_vanished_{entry_id}_{installation_id}"
    if long_missing:
        _create(
            hass,
            issue_id,
            "register_vanished",
            ir.IssueSeverity.WARNING,
            registers=", ".join(sorted(set(long_missing))),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
