"""Where register values come from. Polling is the only source today (WebSocket: P10.7)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .api import ThermiaApi
from .models import RegisterValue, Snapshot


class ValueSource(Protocol):
    async def fetch(self, groups: Iterable[str]) -> Snapshot:
        """Current values of every register in ``groups``."""
        ...


class PollingSource:
    """Reads the needed groups one request each; unavailable groups (``[]``) add nothing."""

    def __init__(self, api: ThermiaApi, installation_id: int) -> None:
        self._api = api
        self._installation_id = installation_id

    async def fetch(self, groups: Iterable[str]) -> Snapshot:
        values: dict[int, RegisterValue] = {}
        for group in groups:
            for spec, value in await self._api.get_group_registers(self._installation_id, group):
                values[spec.register_id] = value
        return Snapshot(values)
