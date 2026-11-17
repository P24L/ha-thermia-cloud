"""Config flow: sign in, then pick installations when the account has several."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .client.api import ThermiaApi
from .client.auth import ThermiaAuth
from .client.config import fetch_config
from .client.errors import (
    AuthError,
    PolicyAcceptanceError,
    ThermiaError,
)
from .client.http import ThermiaHttp
from .client.models import Installation
from .const import (
    CONF_DEBUG_ATTRIBUTES,
    CONF_EXPOSE_UNKNOWN,
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_READ_ONLY,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_HIDDEN,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Probe:
    """What a successful sign-in tells us."""

    subject: str
    refresh_token: str | None
    installations: list[Installation]


async def async_probe(hass: HomeAssistant, username: str, password: str) -> Probe:
    """Sign in and list the installations (test-before-configure). Raises ``ThermiaError``."""
    session = async_get_clientsession(hass)
    config = await fetch_config(session)
    auth = ThermiaAuth(config, username, password, user_agent=USER_AGENT)
    try:
        api = ThermiaApi(ThermiaHttp(session, auth, config.api_base_url))
        installations = await api.list_installations()
        subject = auth.subject or username.strip().lower()
        return Probe(subject, auth.refresh_token, installations)
    finally:
        await auth.close()


def error_key(err: ThermiaError) -> str:
    """Map a client error to a config-flow error key."""
    if isinstance(err, AuthError):
        return "invalid_auth"
    if isinstance(err, PolicyAcceptanceError):
        return "policy_acceptance_required"
    # NetworkError, LoginFlowError and API errors: nothing the user can fix by re-typing
    return "cannot_connect"


class ThermiaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._username = ""
        self._password = ""
        self._probe: Probe | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            try:
                self._probe = await async_probe(self.hass, self._username, self._password)
            except ThermiaError as err:
                errors["base"] = error_key(err)
            except Exception:
                _LOGGER.exception("Unexpected error during sign-in")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(self._probe.subject)
                self._abort_if_unique_id_configured()
                if not self._probe.installations:
                    return self.async_abort(reason="no_installations")
                if len(self._probe.installations) > 1:
                    return await self.async_step_installations()
                return self._create_entry([self._probe.installations[0].id])

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_installations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._probe is not None
        if user_input is not None:
            return self._create_entry([int(i) for i in user_input[CONF_INSTALLATIONS]])
        options = [
            SelectOptionDict(
                value=str(inst.id),
                label=f"{inst.name} ({inst.model or 'Thermia'}, "
                f"{'online' if inst.is_online else 'offline'})",
            )
            for inst in self._probe.installations
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INSTALLATIONS, default=[o["value"] for o in options]
                ): SelectSelector(SelectSelectorConfig(options=options, multiple=True)),
            }
        )
        return self.async_show_form(step_id="installations", data_schema=schema)

    def _create_entry(self, installation_ids: list[int]) -> ConfigFlowResult:
        assert self._probe is not None
        return self.async_create_entry(
            title=self._username,
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_REFRESH_TOKEN: self._probe.refresh_token,
            },
            options={
                CONF_INSTALLATIONS: installation_ids,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_READ_ONLY: False,
                CONF_TIMEOUT: DEFAULT_TIMEOUT,
                CONF_SHOW_HIDDEN: False,
                CONF_EXPOSE_UNKNOWN: True,
                CONF_DEBUG_ATTRIBUTES: False,
            },
        )
