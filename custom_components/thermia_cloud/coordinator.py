"""One ``DataUpdateCoordinator`` per installation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .catalog.planner import EntityPlan
from .client.api import ThermiaApi
from .client.errors import AuthError, RateLimitError, ThermiaError
from .client.models import Installation, RegisterSpec, RegisterValue
from .client.sources import ValueSource
from .client.visibility import RegisterLookup, VisibilityParseError, parse_condition
from .const import DOMAIN, VANISHED_AFTER_DAYS
from .discovery import Discovery
from .repairs import sync_vanished

_LOGGER = logging.getLogger(__name__)

DRIFT_MIN_INTERVAL = timedelta(minutes=10)  # at most one automatic rediscovery per 10 minutes

FAST_POLL = timedelta(seconds=5)  # after a write, until the read-back matches
FAST_POLL_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class CoordinatorData:
    """Comparable snapshot, so entities only write state when something changed."""

    values: Mapping[int, RegisterValue]  # by register_id
    inactive: frozenset[int]  # register ids hidden by a runtime condition / disabled value
    # register id -> value written and not confirmed yet. Part of the comparison on purpose:
    # when a write is confirmed or given up, entities must re-render even if no register changed.
    pending: Mapping[int, float] = field(default_factory=dict)


class ThermiaCoordinator(DataUpdateCoordinator[CoordinatorData]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        installation: Installation,
        source: ValueSource,
        api: ThermiaApi,
        discovery: Discovery,
        interval: int,
        missing_store: Store[dict[str, str]] | None = None,
        missing_since: dict[int, datetime] | None = None,
        last_drift: datetime | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{installation.id}",
            update_interval=timedelta(seconds=interval),
            always_update=False,
        )
        self.installation = installation
        self.api = api
        self.discovery = discovery
        self._base_interval = timedelta(seconds=interval)
        # register id -> (value we wrote, give up at); shown as the ``pending_value`` attribute
        self.pending: dict[
            int, tuple[float, datetime, datetime]
        ] = {}  # value, give up at, written at
        self._source = source
        self._groups: tuple[str, ...] = discovery.groups  # all until the plan narrows it
        self._plans: tuple[EntityPlan, ...] = ()
        self._by_id = {s.register_id: s for s in discovery.all_specs}
        self._conditions: dict[str, object] = {}
        self._reported_missing = False
        # register id -> first time it was missing (persisted, so a restart does not reset it)
        self._missing_store = missing_store
        self.missing_since: dict[int, datetime] = missing_since or {}
        # Called when the cloud's register set no longer matches our discovery (see _check_drift)
        self.on_drift: Callable[[], None] | None = None
        self._last_drift = last_drift  # persisted: a reload must not reset the rate limit

    def spec(self, register_id: int) -> RegisterSpec | None:
        return self._by_id.get(register_id)

    def track_write(self, register_id: int, value: float) -> None:
        """The cloud accepted ``value``: poll fast until the register shows it (max 30 s)."""
        now = dt_util.utcnow()
        self.pending[register_id] = (value, now + FAST_POLL_WINDOW, now)
        self.update_interval = FAST_POLL
        self.async_update_listeners()
        self.hass.async_create_task(self.async_request_refresh())

    def _check_drift(self, values: Mapping[int, RegisterValue]) -> None:
        """Rediscover when the cloud returns a register we have never seen.

        Switching a circuit between *Curve* and *Constant* makes new registers appear. (Registers
        that merely vanish need nothing: their entities turn unavailable and are back when the
        register returns.) At most one rediscovery per 10 minutes, persisted across reloads.
        """
        if not any(i not in self._by_id for i in values) or self.on_drift is None:
            return
        now = dt_util.utcnow()
        if self._last_drift is not None and now - self._last_drift < DRIFT_MIN_INTERVAL:
            return
        self._last_drift = now
        self._save_state(immediately=True)  # a reload follows right away
        _LOGGER.info("The cloud returned an unknown register; rediscovering the registers")
        self.on_drift()

    def _track_vanished(self, missing: Mapping[int, str]) -> None:
        """Remember since when registers are missing; long-missing ones raise a Repair issue."""
        now = dt_util.utcnow()
        changed = False
        for register_id in list(self.missing_since):
            if register_id not in missing:
                del self.missing_since[register_id]
                changed = True
        for register_id in missing:
            if register_id not in self.missing_since:
                self.missing_since[register_id] = now
                changed = True
        limit = now - timedelta(days=VANISHED_AFTER_DAYS)
        long_missing = [name for i, name in missing.items() if self.missing_since[i] <= limit]
        if self.config_entry is not None:
            sync_vanished(self.hass, self.config_entry.entry_id, self.installation.id, long_missing)
        if changed:
            self._save_state()

    def _save_state(self, *, immediately: bool = False) -> None:
        if self._missing_store is None:
            return

        def data() -> dict[str, str]:
            state = {str(i): t.isoformat() for i, t in self.missing_since.items()}
            if self._last_drift is not None:
                state["last_drift"] = self._last_drift.isoformat()
            return state

        if immediately:
            self.hass.async_create_task(self._missing_store.async_save(data()))
        else:
            self._missing_store.async_delay_save(data, 10)

    def _settle_pending(self, values: Mapping[int, RegisterValue]) -> None:
        now = dt_util.utcnow()
        for register_id, (wanted, give_up_at, written_at) in list(self.pending.items()):
            current = values.get(register_id)
            if current is not None and current.value is not None and current.value == wanted:
                del self.pending[register_id]
                _LOGGER.debug(
                    "Register %s read back as %s after %.1f s",
                    register_id,
                    wanted,
                    (now - written_at).total_seconds(),
                )
            elif now >= give_up_at:
                del self.pending[register_id]
                log = _LOGGER.warning if self.installation.is_online else _LOGGER.info
                log(
                    "Written value %s for register %s not seen in the cloud yet (%s)",
                    wanted,
                    register_id,
                    "the device is offline, the cloud queues the change"
                    if not self.installation.is_online
                    else "it may still be applied",
                )
        if not self.pending:
            self.update_interval = self._base_interval

    def set_plans(self, plans: tuple[EntityPlan, ...], groups: tuple[str, ...]) -> None:
        """Called once the plan exists: runtime conditions and the groups worth polling."""
        self._plans = plans
        self._groups = groups
        if self.data is not None:  # the first poll ran before there was a plan
            self.async_set_updated_data(
                CoordinatorData(
                    self.data.values, self._inactive(self.data.values), self.data.pending
                )
            )

    async def _async_update_data(self) -> CoordinatorData:
        try:
            snapshot = await self._source.fetch(self._groups)
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except ThermiaError as err:
            raise UpdateFailed(str(err)) from err

        values = snapshot.values
        polled = set(self._groups)
        # Registers that the cloud only returns in some state are *expected* to come and go:
        # their entities just turn unavailable, with no warning and no Repair issue.
        missing_plans = [
            p
            for p in self._plans
            if p.group_name in polled and p.register_id not in values and not p.state_dependent
        ]
        missing = [p.register_name for p in missing_plans]
        if missing and not self._reported_missing:
            _LOGGER.warning("Registers no longer returned by the cloud: %s", sorted(set(missing)))
            self._reported_missing = True
        elif not missing:
            self._reported_missing = False
        self._track_vanished({p.register_id: p.register_name for p in missing_plans})
        self._check_drift(values)
        self._settle_pending(values)
        return CoordinatorData(
            values, self._inactive(values), {i: p[0] for i, p in self.pending.items()}
        )

    def _inactive(self, values: Mapping[int, RegisterValue]) -> frozenset[int]:
        lookup = RegisterLookup(
            (self._by_id[i].group_name, self._by_id[i].name, v.value)
            for i, v in values.items()
            if i in self._by_id
        )
        inactive: set[int] = set()
        for plan in self._plans:
            value = values.get(plan.register_id)
            if value is None or value.value is None:
                continue
            if plan.disabled_value is not None and value.value == plan.disabled_value:
                inactive.add(plan.register_id)
            elif plan.runtime_condition:
                try:
                    condition = parse_condition(plan.runtime_condition)
                except VisibilityParseError:
                    continue
                if not condition.evaluate(lookup.resolver(plan.group_name)).visible:
                    inactive.add(plan.register_id)
        return frozenset(inactive)
