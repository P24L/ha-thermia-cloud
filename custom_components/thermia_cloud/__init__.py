"""Thermia Cloud (unofficial) integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .catalog.labels import (
    LabelResolver,
    async_load_bundled,
    async_load_curated,
    async_load_overrides,
    filter_label_keys,
    pick_culture,
)
from .catalog.loader import async_load_catalog
from .catalog.planner import (
    EntityPlan,
    PlannerOptions,
    PlanNote,
    build_plan,
    resolve_name_collisions,
)
from .catalog.schema import Catalog
from .client.api import ThermiaApi
from .client.auth import ThermiaAuth
from .client.config import ThermiaConfig, fetch_config
from .client.errors import AuthError, PolicyAcceptanceError, ThermiaError
from .client.http import ThermiaHttp
from .client.models import Installation, RegisterValue
from .client.sources import PollingSource
from .client.visibility import VisibilityParseError, parse_condition
from .const import (
    CONF_EXPOSE_UNKNOWN,
    CONF_INSTALLATIONS,
    CONF_LABEL_LANGUAGE,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_HIDDEN,
    CONF_TIMEOUT,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    LABEL_LANGUAGE_AUTO,
    USER_AGENT,
)
from .coordinator import ThermiaCoordinator
from .discovery import Discovery, discover, merge_remembered
from .entity import device_identifier
from .repairs import sync_discovery_empty, sync_policy_acceptance
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]
DISCOVERY_MAX_AGE = 24 * 3600
STORE_VERSION = 1


@dataclass(slots=True)
class InstallationRuntime:
    installation: Installation
    coordinator: ThermiaCoordinator
    plans: tuple[EntityPlan, ...]
    names: dict[str, str]
    notes: tuple[PlanNote, ...]
    devices: frozenset[str]


@dataclass(slots=True)
class ThermiaRuntime:
    auth: ThermiaAuth
    api: ThermiaApi
    catalog: Catalog
    labels: LabelResolver
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
    timeout = float(entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
    http = ThermiaHttp(session, auth, config.api_base_url, timeout=timeout)
    return config, auth, ThermiaApi(http)


def _discovery_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    return Store(hass, STORE_VERSION, f"{DOMAIN}.discovery.{entry.entry_id}")


async def _load_discovery(
    hass: HomeAssistant, entry: ThermiaConfigEntry, api: ThermiaApi, installation_id: int
) -> Discovery:
    """Cached discovery; refreshed daily, and the cache is used when the cloud is unreachable."""
    store = _discovery_store(hass, entry)
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
    fresh = merge_remembered(cached, fresh)
    cache[str(installation_id)] = fresh.to_json()
    await store.async_save(cache)
    return fresh


async def async_rediscover(
    hass: HomeAssistant,
    entry: ThermiaConfigEntry,
    installation_id: int,
    api: ThermiaApi | None = None,
    *,
    forget: bool = False,
) -> None:
    """Read everything again and reload the entry (button, or automatic on register drift).

    ``forget`` drops the remembered specs of vanished registers (the *Rediscover* button).
    ``api`` is passed explicitly when the entry is still being set up (``runtime_data`` is not
    there yet): the first poll can already notice that the cached register set is outdated.
    """
    fresh = await discover(api or entry.runtime_data.api, installation_id)
    store = _discovery_store(hass, entry)
    cache = await store.async_load() or {}
    previous: Discovery | None = None
    if (raw := cache.get(str(installation_id))) is not None:
        try:
            previous = Discovery.from_json(raw)
        except KeyError, TypeError, ValueError:
            previous = None
    fresh = merge_remembered(previous, fresh, forget=forget)
    cache[str(installation_id)] = fresh.to_json()
    await store.async_save(cache)
    hass.config_entries.async_schedule_reload(entry.entry_id)


def _drift_handler(
    hass: HomeAssistant, entry: ThermiaConfigEntry, installation_id: int, api: ThermiaApi
) -> Callable[[], None]:
    """Callback for the coordinator: rediscover in the background (never inside a poll)."""

    async def rediscover() -> None:
        try:
            await async_rediscover(hass, entry, installation_id, api)
        except ThermiaError as err:
            _LOGGER.warning("Automatic rediscovery failed: %s", err)

    def handler() -> None:
        entry.async_create_background_task(hass, rediscover(), f"{DOMAIN}_rediscover")

    return handler


def _labels_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    return Store(hass, STORE_VERSION, f"{DOMAIN}.labels.{entry.entry_id}")


async def async_refresh_labels(hass: HomeAssistant, entry: ThermiaConfigEntry) -> None:
    """*Refresh names* button: fetch Thermia's texts for the chosen culture, then reload."""
    runtime = entry.runtime_data
    culture = runtime.labels.culture
    texts = await runtime.api.get_localization(culture)
    value_names = {
        v.name
        for r in runtime.installations
        for s in r.coordinator.discovery.all_specs
        for v in s.value_names
    }
    await _labels_store(hass, entry).async_save(
        {"culture": culture, "labels": filter_label_keys(texts, value_names)}
    )
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


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
        language = entry.options.get(CONF_LABEL_LANGUAGE, LABEL_LANGUAGE_AUTO)
        if language == LABEL_LANGUAGE_AUTO:
            language = hass.config.language
        stored = await _labels_store(hass, entry).async_load() or {}
        labels = LabelResolver(
            language,
            bundled,
            curated=await async_load_curated(language),
            curated_fallback=await async_load_curated("en"),
            overrides=await async_load_overrides(),
            refreshed=stored.get("labels")
            if stored.get("culture") == pick_culture(language, bundled)
            else None,
        )
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        options = PlannerOptions(
            show_hidden=bool(entry.options.get(CONF_SHOW_HIDDEN, False)),
            expose_unknown=bool(entry.options.get(CONF_EXPOSE_UNKNOWN, True)),
        )
        missing_store: Store[dict[str, str]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.missing.{entry.entry_id}"
        )
        missing_raw = await missing_store.async_load() or {}
        runtimes: list[InstallationRuntime] = []
        device_registry = dr.async_get(hass)

        for installation in installations:
            discovery = await _load_discovery(hass, entry, api, installation.id)
            sync_discovery_empty(hass, entry.entry_id, installation.id, not discovery.specs)
            coordinator = ThermiaCoordinator(
                hass,
                entry,
                installation,
                PollingSource(api, installation.id),
                api,
                discovery,
                interval,
                missing_store,
                {
                    int(i): datetime.fromisoformat(t)
                    for i, t in missing_raw.items()
                    if i.isdigit() and installation_owns(discovery, int(i))
                },
                datetime.fromisoformat(missing_raw["last_drift"])
                if "last_drift" in missing_raw
                else None,
            )
            coordinator.on_drift = _drift_handler(hass, entry, installation.id, api)
            await coordinator.async_config_entry_first_refresh()
            assert coordinator.data is not None
            values = coordinator.data.values
            remembered = {r.spec.register_id for r in discovery.remembered}
            registers = [
                # remembered registers are planned even though the cloud returns no value now
                (
                    spec,
                    values.get(spec.register_id)
                    or RegisterValue(spec.register_id, None, None, None),
                )
                for spec in discovery.all_specs
                if spec.register_id in values or spec.register_id in remembered
            ]
            plan = build_plan(
                registers,
                catalog,
                history={h.register_index: h for h in discovery.history},
                options=replace(
                    options, has_indoor_sensor=await _has_indoor_sensor(api, installation.id)
                ),
                now=datetime.now(),
            )
            names = resolve_name_collisions(
                plan.entities,
                lambda p: labels.label(p.label_key, p.translation_key),
                lambda p: labels.label(p.group_name),
            )
            _enable_integration_disabled(hass, installation.id, plan.entities)
            coordinator.set_plans(plan.entities, _needed_groups(hass, plan.entities, discovery))
            _register_devices(device_registry, entry, installation, catalog, plan.entities, labels)
            runtimes.append(
                InstallationRuntime(
                    installation,
                    coordinator,
                    plan.entities,
                    names,
                    plan.notes,
                    frozenset({"main"} | {p.device for p in plan.entities}),
                )
            )
    except AuthError as err:
        await auth.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except PolicyAcceptanceError as err:
        await auth.close()
        sync_policy_acceptance(hass, entry.entry_id, True)
        raise ConfigEntryNotReady(str(err)) from err
    except ThermiaError as err:
        await auth.close()
        raise ConfigEntryNotReady(str(err)) from err
    except BaseException:
        await auth.close()
        raise

    sync_policy_acceptance(hass, entry.entry_id, False)
    entry.runtime_data = ThermiaRuntime(auth, api, catalog, labels, runtimes)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _has_indoor_sensor(api: ThermiaApi, installation_id: int) -> bool | None:
    """``hasIndoorTempSensor`` of the installation status; ``None`` when it cannot be read."""
    try:
        status = await api.get_status(installation_id)
    except AuthError:
        raise
    except ThermiaError:
        return None
    value = status.get("hasIndoorTempSensor")
    return value if isinstance(value, bool) else None


def installation_owns(discovery: Discovery, register_id: int) -> bool:
    return any(spec.register_id == register_id for spec in discovery.all_specs)


def _enable_integration_disabled(
    hass: HomeAssistant, installation_id: int, plans: tuple[EntityPlan, ...]
) -> None:
    """Enable entities the integration disabled earlier but the plan now enables.

    Home Assistant remembers the default an entity was created with and never re-reads it, so an
    entity created before the catalog knew it (or before it was switched on) would stay off for
    good. Only ``disabled_by = integration`` is touched: an entity the user disabled stays off.
    """
    registry = er.async_get(hass)
    for plan in plans:
        if not plan.default_enabled:
            continue
        entity_id = registry.async_get_entity_id(
            plan.platform, DOMAIN, f"{installation_id}_{plan.key}"
        )
        entity = registry.async_get(entity_id) if entity_id else None
        if entity is not None and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_id, disabled_by=None)


def _needed_groups(
    hass: HomeAssistant, plans: tuple[EntityPlan, ...], discovery: Discovery
) -> tuple[str, ...]:
    """Groups holding an enabled entity, plus groups its runtime condition looks at.

    "Enabled" follows the entity registry (the user's choice); entities not registered yet use
    the plan's default. HA reloads the entry after the user enables an entity, which brings
    this set up to date; disabling does not reload, so we over-poll until the next reload.
    """
    registry = er.async_get(hass)
    installation_id = discovery.installation_id
    groups_by_name: dict[str, set[str]] = {}
    for spec in discovery.all_specs:
        groups_by_name.setdefault(spec.name, set()).add(spec.group_name)

    needed: set[str] = set()
    for plan in plans:
        entity_id = registry.async_get_entity_id(
            plan.platform, DOMAIN, f"{installation_id}_{plan.key}"
        )
        entry = registry.async_get(entity_id) if entity_id else None
        enabled = entry.disabled_by is None if entry else plan.default_enabled
        if not enabled:
            continue
        needed.add(plan.group_name)
        if plan.runtime_condition:
            try:
                refs = parse_condition(plan.runtime_condition).refs
            except VisibilityParseError:
                continue
            for name in refs:
                candidates = groups_by_name.get(name, set())
                if plan.group_name not in candidates:
                    needed |= candidates
    return tuple(g for g in discovery.groups if g in needed)


def _register_devices(
    registry: dr.DeviceRegistry,
    entry: ConfigEntry,
    installation: Installation,
    catalog: Catalog,
    plans: tuple[EntityPlan, ...],
    labels: LabelResolver,
) -> None:
    main = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={device_identifier(installation.id, "main")},
        manufacturer="Thermia",
        model=installation.model or None,
        model_id=installation.model_id,
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
            name=labels.label(key, device.translation_key if device else None),
        )


async def async_unload_entry(hass: HomeAssistant, entry: ThermiaConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.auth.close()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ThermiaConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """The user may delete devices that are no longer part of the current plan."""
    active = {
        device_identifier(runtime.installation.id, device)
        for runtime in entry.runtime_data.installations
        for device in runtime.devices
    }
    return not (device_entry.identifiers & active)
