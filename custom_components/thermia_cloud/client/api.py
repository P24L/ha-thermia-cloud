"""Read-side API of the Thermia Online cloud (writes follow in roadmap P2.8)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from .errors import ApiError, RateLimitError, RegisterWriteError
from .http import ThermiaHttp
from .models import (
    Group,
    HistoryRegister,
    Installation,
    InstallationDetail,
    RegisterSpec,
    RegisterValue,
)
from .validation import validate_write


class ThermiaApi:
    def __init__(self, http: ThermiaHttp) -> None:
        self._http = http
        self._write_locks: dict[int, asyncio.Lock] = {}

    async def list_installations(self) -> list[Installation]:
        data = await self._http.request("GET", "/api/v1/installationsInfo")
        return [Installation.from_json(item) for item in data.get("items", [])]

    async def get_installation(self, installation_id: int) -> InstallationDetail:
        data = await self._http.request("GET", f"/api/v1/installations/{installation_id}")
        return InstallationDetail.from_json(data)

    async def get_groups(self, profile_id: int) -> list[Group]:
        data = await self._http.request("GET", f"/api/v1/installationprofiles/{profile_id}/groups")
        return [Group.from_json(item) for item in data]

    async def get_group_registers(
        self, installation_id: int, group_name: str
    ) -> list[tuple[RegisterSpec, RegisterValue]]:
        """Registers of a group. An unavailable group is ``200 []``: an empty list, not an error."""
        data: list[dict[str, Any]] = await self._http.request(
            "GET", f"/api/v1/Registers/Installations/{installation_id}/Groups/{group_name}"
        )
        return [(RegisterSpec.from_json(item), RegisterValue.from_json(item)) for item in data]

    async def get_history_registers(self, installation_id: int) -> list[HistoryRegister]:
        """Registers offered for history; they carry the visibility conditions."""
        data = await self._http.request(
            "GET", f"/api/v1/DataHistory/installation/{installation_id}"
        )
        return [HistoryRegister.from_json(item) for item in data.get("registers", [])]

    async def get_status(self, installation_id: int) -> dict[str, Any]:
        result: dict[str, Any] = await self._http.request(
            "GET", f"/api/v1/installationstatus/{installation_id}/status"
        )
        return result

    async def get_languages(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._http.request("GET", "/api/v1/languages")
        return result

    async def get_localization(self, culture: str) -> dict[str, str]:
        data = await self._http.request("GET", f"/api/v1/localization/{culture}")
        return {item["key"]: item["value"] for item in data.get("resources", [])}

    async def write_register(
        self, installation_id: int, spec: RegisterSpec, value: float
    ) -> float | int:
        """Validate, then POST the value; returns what was sent.

        Writes to one installation are serialized. The cloud answers 200 even when the device is
        offline (the value is queued), so success means *accepted*, not *applied*.
        """
        to_send = validate_write(spec, value)
        lock = self._write_locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            try:
                await self._http.request(
                    "POST",
                    f"/api/v1/Registers/Installations/{installation_id}/Registers",
                    json={
                        "registerSpecificationId": spec.register_id,
                        "registerValue": to_send,
                        "clientUuid": str(uuid.uuid4()),
                    },
                )
            except RateLimitError:
                raise
            except ApiError as err:
                raise RegisterWriteError(f"the cloud answered HTTP {err.status}") from err
        return to_send
