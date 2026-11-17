"""Thermia Cloud (unofficial) integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .catalog.labels import LabelResolver, async_load_bundled
from .catalog.loader import async_load_catalog
from .catalog.planner import EntityPlan, PlannerOptions, build_plan, resolve_name_collisions
from .catalog.schema import Catalog
from .client.api import ThermiaApi
from .client.auth import ThermiaAuth
from .client.config import ThermiaConfig, fetch_config
from .client.errors import AuthError, ThermiaError
from .client.http import ThermiaHttp
from .client.models import Installation
from .client.sources import PollingSource
from .const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_HIDDEN,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    USER_AGENT,
)
from .coordinator import ThermiaCoordinator
from .discovery import Discovery, discover
from .entity import device_identifier

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
DISCOVERY_MAX_AGE = 24 * 3600
STORE_VERSION = 1


@dataclass(slots=True)
class InstallationRuntime:
    installation: Installation
    coordinator: ThermiaCoordinator
    plans: tuple[EntityPlan, ...]
    names: dict[str, str]


@dataclass(slots=True)
class ThermiaRuntime:
    auth: ThermiaAuth
    api: ThermiaApi
    catalog: Catalog
    installations: list[InstallationRuntime]


type ThermiaConfigEntry = ConfigEntry[ThermiaRuntime]


async def async_build_client(
    hass: HomeAssistant, entry: ThermiaConfigEntry
) -> tuple[ThermiaConfig, ThermiaAuth, ThermiaApi]:
    """Create the client for an entry; the rotated refresh token is persisted on every change."""
    session = async_get_clientsession(hass)
    config = await fetch_config(session)

    def remember(token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: token}
        )

    auth = ThermiaAuth(
        config,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        on_refresh_token=remember,
        user_agent=USER_AGENT,
    )
    return config, auth, ThermiaApi(ThermiaHttp(session, auth, config.api_base_url))


async def _load_discovery(
    hass: HomeAssistant, entry: ThermiaConfigEntry, api: ThermiaApi, installation_id: int
) -> Discovery:
    """Cached discovery; refreshed daily, and the cache is used when the cloud is unreachable."""
    store: Store[dict[str, Any]] = Store(
        hass, STORE_VERSION, f"{DOMAIN}.discovery.{entry.entry_id}"
    )
    cache = await store.async_load() or {}
    cached: Discovery | None = None
    if (raw := cache.get(str(installation_id))) is not None:
        try:
            cached = Discovery.from_json(raw)
        except KeyError, TypeError, ValueError:
            _LOGGER.debug("Discarding unreadable discovery cache")
    if cached is not None and cached.age_seconds(datetime.now(UTC)) < DISCOVERY_MAX_AGE:
        return cached
    try:
        fresh = await discover(api, installation_id)
    except AuthError:
        raise
    except ThermiaError:
        if cached is not None:
            _LOGGER.warning("Cloud unreachable, using cached discovery")
            return cached
        raise
    cache[str(installation_id)] = fresh.to_json()
    await store.async_save(cache)
    return fresh


async def async_setup_entry(hass: HomeAssistant, entry: ThermiaConfigEntry) -> bool:
    try:
        _, auth, api = await async_build_client(hass, entry)
    except ThermiaError as err:
        raise ConfigEntryNotReady(str(err)) from err

    try:
        catalog = await async_load_catalog()
        bundled = await async_load_bundled()
        wanted = set(entry.options.get(CONF_INSTALLATIONS, []))
        installations = [i for i in await api.list_installations() if not wanted or i.id in wanted]
        labels = LabelResolver(hass.config.language, bundled)
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        options = PlannerOptions(show_hidden=bool(entry.options.get(CONF_SHOW_HIDDEN, False)))
        runtimes: list[InstallationRuntime] = []
        device_registry = dr.async_get(hass)

        for installation in installations:
            discovery = await _load_discovery(hass, entry, api, installation.id)
            coordinator = ThermiaCoordinator(
                hass, entry, installation, PollingSource(api, installation.id), discovery, interval
            )
            await coordinator.async_config_entry_first_refresh()
            assert coordinator.data is not None
            registers = [
                (spec, coordinator.data.values[spec.register_id])
                for spec in discovery.specs
                if spec.register_id in coordinator.data.values
            ]
            plan = build_plan(
                registers,
                catalog,
                history={h.register_index: h for h in discovery.history},
                options=options,
                now=datetime.now(),
            )
            names = resolve_name_collisions(
                plan.entities,
                lambda p: labels.label(p.label_key, p.translation_key),
                lambda p: labels.label(p.group_name),
            )
            coordinator.set_plans(plan.entities, _needed_groups(plan.entities, discovery))
            _register_devices(device_registry, entry, installation, catalog, plan.entities)
            runtimes.append(InstallationRuntime(installation, coordinator, plan.entities, names))
    except AuthError as err:
        await auth.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except ThermiaError as err:
        await auth.close()
        raise ConfigEntryNotReady(str(err)) from err
    except BaseException:
        await auth.close()
        raise

    entry.runtime_data = ThermiaRuntime(auth, api, catalog, runtimes)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _needed_groups(plans: tuple[EntityPlan, ...], discovery: Discovery) -> tuple[str, ...]:
    """Groups with an enabled entity. (Entity-registry awareness follows with P4.5 review.)"""
    wanted = {p.group_name for p in plans if p.default_enabled}
    return tuple(g for g in discovery.groups if g in wanted) or discovery.groups


def _register_devices(
    registry: dr.DeviceRegistry,
    entry: ConfigEntry,
    installation: Installation,
    catalog: Catalog,
    plans: tuple[EntityPlan, ...],
) -> None:
    main = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={device_identifier(installation.id, "main")},
        manufacturer="Thermia",
        model=installation.model or None,
        name=installation.name or "Thermia heat pump",
        sw_version=installation.firmware_version,
    )
    for key in sorted({p.device for p in plans} - {"main"}):
        device = catalog.devices.get(key)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={device_identifier(installation.id, key)},
            manufacturer="Thermia",
            via_device_id=main.id,
            translation_key=device.translation_key if device else None,
            name=None if device and device.translation_key else key,
        )


async def async_unload_entry(hass: HomeAssistant, entry: ThermiaConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.auth.close()
    return unloaded
