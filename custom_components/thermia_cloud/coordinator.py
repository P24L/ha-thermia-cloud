"""One ``DataUpdateCoordinator`` per installation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .catalog.planner import EntityPlan
from .client.errors import AuthError, RateLimitError, ThermiaError
from .client.models import Installation, RegisterValue
from .client.sources import ValueSource
from .client.visibility import RegisterLookup, VisibilityParseError, parse_condition
from .const import DOMAIN
from .discovery import Discovery

_LOGGER = logging.getLogger(__name__)


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
        self.discovery = discovery
        self._source = source
        self._groups: tuple[str, ...] = discovery.groups  # all until the plan narrows it
        self._plans: tuple[EntityPlan, ...] = ()
        self._by_id = {s.register_id: s for s in discovery.specs}
        self._conditions: dict[str, object] = {}
        self._reported_missing = False

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
        missing = [p.register_name for p in self._plans if p.register_id not in values]
        if missing and not self._reported_missing:
            _LOGGER.warning("Registers no longer returned by the cloud: %s", sorted(set(missing)))
            self._reported_missing = True
        elif not missing:
            self._reported_missing = False
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
