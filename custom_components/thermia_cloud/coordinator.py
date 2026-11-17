"""One ``DataUpdateCoordinator`` per installation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .catalog.planner import EntityPlan
from .client.api import ThermiaApi
from .client.errors import AuthError, RateLimitError, ThermiaError
from .client.models import Installation, RegisterSpec, RegisterValue
from .client.sources import ValueSource
from .client.visibility import RegisterLookup, VisibilityParseError, parse_condition
from .const import DOMAIN
from .discovery import Discovery

_LOGGER = logging.getLogger(__name__)

FAST_POLL = timedelta(seconds=5)  # after a write, until the read-back matches
FAST_POLL_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class CoordinatorData:
    """Comparable snapshot, so entities only write state when something changed."""

    values: Mapping[int, RegisterValue]  # by register_id
    inactive: frozenset[int]  # register ids hidden by a runtime condition / disabled value


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
        self.pending: dict[int, tuple[float, datetime]] = {}
        self._source = source
        self._groups: tuple[str, ...] = discovery.groups  # all until the plan narrows it
        self._plans: tuple[EntityPlan, ...] = ()
        self._by_id = {s.register_id: s for s in discovery.specs}
        self._conditions: dict[str, object] = {}
        self._reported_missing = False

    def spec(self, register_id: int) -> RegisterSpec | None:
        return self._by_id.get(register_id)

    def track_write(self, register_id: int, value: float) -> None:
        """The cloud accepted ``value``: poll fast until the register shows it (max 30 s)."""
        self.pending[register_id] = (value, dt_util.utcnow() + FAST_POLL_WINDOW)
        self.update_interval = FAST_POLL
        self.async_update_listeners()
        self.hass.async_create_task(self.async_request_refresh())

    def _settle_pending(self, values: Mapping[int, RegisterValue]) -> None:
        now = dt_util.utcnow()
        for register_id, (wanted, give_up_at) in list(self.pending.items()):
            current = values.get(register_id)
            if current is not None and current.value is not None and current.value == wanted:
                del self.pending[register_id]
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
                CoordinatorData(self.data.values, self._inactive(self.data.values))
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
        missing = [
            p.register_name
            for p in self._plans
            if p.group_name in polled and p.register_id not in values
        ]
        if missing and not self._reported_missing:
            _LOGGER.warning("Registers no longer returned by the cloud: %s", sorted(set(missing)))
            self._reported_missing = True
        elif not missing:
            self._reported_missing = False
        self._settle_pending(values)
        return CoordinatorData(values, self._inactive(values))

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
