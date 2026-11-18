"""Config flow: sign in, then pick installations when the account has several."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .catalog.labels import I18N_DIR
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
    CONF_LABEL_LANGUAGE,
    CONF_PASSWORD,
    CONF_READ_ONLY,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_HIDDEN,
    CONF_START_MODE,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    LABEL_LANGUAGE_AUTO,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ThermiaOptionsFlow:
        return ThermiaOptionsFlow()

    def __init__(self) -> None:
        self._username = ""
        self._password = ""
        self._probe: Probe | None = None
        self._installation_ids: list[int] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            self._probe, error = await self._try_probe(self._username, self._password)
            if self._probe is None:
                errors["base"] = error
            else:
                await self.async_set_unique_id(self._probe.subject)
                self._abort_if_unique_id_configured()
                if not self._probe.installations:
                    return self.async_abort(reason="no_installations")
                if len(self._probe.installations) > 1:
                    return await self.async_step_installations()
                self._installation_ids = [self._probe.installations[0].id]
                return await self.async_step_mode()

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
            self._installation_ids = [int(i) for i in user_input[CONF_INSTALLATIONS]]
            return await self.async_step_mode()
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password only; the account is fixed by the entry's unique id."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            probe, error = await self._try_probe(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if probe is not None:
                await self.async_set_unique_id(probe.subject)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: probe.refresh_token,
                    },
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change e-mail and/or password; signing in as a different account is refused."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            probe, error = await self._try_probe(username, user_input[CONF_PASSWORD])
            if probe is not None:
                await self.async_set_unique_id(probe.subject)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    title=username,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_REFRESH_TOKEN: probe.refresh_token,
                    },
                )
            errors["base"] = error
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    async def _try_probe(self, username: str, password: str) -> tuple[Probe | None, str]:
        try:
            return await async_probe(self.hass, username, password), ""
        except ThermiaError as err:
            return None, error_key(err)
        except Exception:
            _LOGGER.exception("Unexpected error during sign-in")
            return None, "unknown"

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Last question of the setup: may the integration change settings on the heat pump?"""
        if user_input is not None:
            return self._create_entry(
                self._installation_ids, read_only=user_input[CONF_START_MODE] == "monitor"
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_START_MODE, default="control"): SelectSelector(
                    SelectSelectorConfig(
                        options=["control", "monitor"],
                        mode=SelectSelectorMode.LIST,
                        translation_key="start_mode",
                    )
                )
            }
        )
        return self.async_show_form(step_id="mode", data_schema=schema)

    def _create_entry(self, installation_ids: list[int], *, read_only: bool) -> ConfigFlowResult:
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
                CONF_READ_ONLY: read_only,
                CONF_TIMEOUT: DEFAULT_TIMEOUT,
                CONF_SHOW_HIDDEN: False,
                CONF_EXPOSE_UNKNOWN: True,
                CONF_DEBUG_ATTRIBUTES: False,
            },
        )


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Fields of a form made of collapsible sections arrive nested one level deep."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


class ThermiaOptionsFlow(OptionsFlowWithReload):
    """Options menu: general settings, installations and registers, names and language."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["general", "registers", "names"])

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            flat = _flatten(user_input)
            return self._save(
                **{
                    CONF_SCAN_INTERVAL: int(flat[CONF_SCAN_INTERVAL]),
                    CONF_TIMEOUT: int(flat[CONF_TIMEOUT]),
                    CONF_READ_ONLY: flat[CONF_READ_ONLY],
                    CONF_DEBUG_ATTRIBUTES: flat[CONF_DEBUG_ATTRIBUTES],
                }
            )
        options = self.config_entry.options
        seconds = {"min": 5, "step": 1, "unit_of_measurement": "s", "mode": NumberSelectorMode.BOX}
        schema = vol.Schema(
            {
                vol.Required("updates"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_SCAN_INTERVAL,
                                default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                            ): NumberSelector(
                                NumberSelectorConfig(
                                    **{
                                        **seconds,
                                        "min": MIN_SCAN_INTERVAL,
                                        "max": MAX_SCAN_INTERVAL,
                                    }
                                )
                            ),
                            vol.Required(
                                CONF_TIMEOUT, default=options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
                            ): NumberSelector(NumberSelectorConfig(**{**seconds, "max": 120})),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("safety"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_READ_ONLY, default=options.get(CONF_READ_ONLY, False)
                            ): BooleanSelector()
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("advanced"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_DEBUG_ATTRIBUTES,
                                default=options.get(CONF_DEBUG_ATTRIBUTES, False),
                            ): BooleanSelector()
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_registers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            flat = _flatten(user_input)
            return self._save(
                **{
                    CONF_INSTALLATIONS: [int(i) for i in flat[CONF_INSTALLATIONS]],
                    CONF_SHOW_HIDDEN: flat[CONF_SHOW_HIDDEN],
                    CONF_EXPOSE_UNKNOWN: flat[CONF_EXPOSE_UNKNOWN],
                }
            )
        if not hasattr(self.config_entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        try:
            installations = await self.config_entry.runtime_data.api.list_installations()
        except ThermiaError:
            return self.async_abort(reason="cannot_connect")
        options = self.config_entry.options
        choices = [
            SelectOptionDict(
                value=str(i.id),
                label=(
                    f"{i.name} ({i.model or 'Thermia'}, {'online' if i.is_online else 'offline'})"
                ),
            )
            for i in installations
        ]
        chosen = [str(i) for i in options.get(CONF_INSTALLATIONS, [])] or [
            c["value"] for c in choices
        ]
        schema = vol.Schema(
            {
                vol.Required("installations"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_INSTALLATIONS, default=chosen): SelectSelector(
                                SelectSelectorConfig(options=choices, multiple=True)
                            )
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required("visibility"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_SHOW_HIDDEN, default=options.get(CONF_SHOW_HIDDEN, False)
                            ): BooleanSelector(),
                            vol.Required(
                                CONF_EXPOSE_UNKNOWN,
                                default=options.get(CONF_EXPOSE_UNKNOWN, True),
                            ): BooleanSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
            }
        )
        return self.async_show_form(step_id="registers", data_schema=schema)

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**{CONF_LABEL_LANGUAGE: user_input[CONF_LABEL_LANGUAGE]})
        cultures = sorted(p.stem for p in I18N_DIR.glob("*.json") if not p.name.startswith("_"))
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LABEL_LANGUAGE,
                    default=self.config_entry.options.get(CONF_LABEL_LANGUAGE, LABEL_LANGUAGE_AUTO),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[LABEL_LANGUAGE_AUTO, *cultures],
                        translation_key="label_language",
                    )
                )
            }
        )
        return self.async_show_form(step_id="names", data_schema=schema)
