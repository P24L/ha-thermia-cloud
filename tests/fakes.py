"""A fake ``ThermiaApi`` backed by the iTec fixtures, for integration tests."""

import json
from pathlib import Path
from typing import Any

from custom_components.thermia_cloud.client.errors import RegisterWriteError
from custom_components.thermia_cloud.client.models import (
    Group,
    HistoryRegister,
    Installation,
    InstallationDetail,
    RegisterSpec,
    RegisterValue,
)
from custom_components.thermia_cloud.client.validation import validate_write

FIXTURES = Path(__file__).parent / "fixtures" / "itec_profile_1005"
INSTALLATION_ID = 42


class FakeAuth:
    subject = "sub-1"
    refresh_token = "refresh-1"

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeApi:
    def __init__(self) -> None:
        self.error: Exception | None = None  # raised by every call when set
        self.calls: list[str] = []
        self.hide: set[str] = set()  # register names the cloud stops returning
        self.overrides: dict[str, float] = {}  # register name -> value
        self.installation_ids = [INSTALLATION_ID]
        self.group_calls: list[str] = []  # groups read, in order
        self.writes: list[tuple[int, float]] = []  # (register id, value) the "cloud" accepted
        self.values: dict[int, float] = {}  # register id -> current value (after writes)
        self.apply_writes = True  # False: accepted but not visible yet (queued / offline device)
        self.write_error: Exception | None = None  # raised instead of accepting a write
        self._queued: list[tuple[int, float]] = []
        self.extra: list[
            dict[str, Any]
        ] = []  # extra raw registers appended to the temperatures group

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    async def list_installations(self) -> list[Installation]:
        self._check("list_installations")
        return [
            Installation(i, f"Test installation {i}", "iTec", True, "1.0", "AA:BB:CC:00:00:01")
            for i in self.installation_ids
        ]

    async def get_installation(self, installation_id: int) -> InstallationDetail:
        self._check("get_installation")
        return InstallationDetail(installation_id, 1005, None)

    async def get_groups(self, profile_id: int) -> list[Group]:
        self._check("get_groups")
        return [
            Group.from_json(g) for g in json.loads((FIXTURES / "profile_groups.json").read_text())
        ]

    async def get_group_registers(
        self, installation_id: int, group_name: str
    ) -> list[tuple[RegisterSpec, RegisterValue]]:
        self._check("get_group_registers")
        self.group_calls.append(group_name)
        raw: list[dict[str, Any]] = json.loads((FIXTURES / f"group_{group_name}.json").read_text())
        if group_name == "REG_GROUP_TEMPERATURES":
            raw = [*raw, *self.extra]
        out = []
        for item in raw:
            if item["registerName"] in self.hide:
                continue
            if item["registerId"] in self.values:
                item = {**item, "registerValue": self.values[item["registerId"]]}
            elif item["registerName"] in self.overrides:
                item = {**item, "registerValue": self.overrides[item["registerName"]]}
            out.append((RegisterSpec.from_json(item), RegisterValue.from_json(item)))
        return out

    async def get_history_registers(self, installation_id: int) -> list[HistoryRegister]:
        self._check("get_history_registers")
        data = json.loads((FIXTURES / "history_registers.json").read_text())
        return [HistoryRegister.from_json(r) for r in data["registers"]]

    async def get_localization(self, culture: str) -> dict[str, str]:
        self._check("get_localization")
        return {
            "REG_OPER_DATA_OUTDOOR_TEMP_MA_SA": f"Fresh outdoor text ({culture})",
            "ALARM_SOMETHING": "must not be kept",
        }

    async def write_register(self, installation_id: int, spec: RegisterSpec, value: float) -> float:
        self._check("write_register")
        sent = validate_write(spec, value)  # the real validation, as the real client does
        if self.write_error is not None:
            raise self.write_error
        self.writes.append((spec.register_id, sent))
        if self.apply_writes:
            self.values[spec.register_id] = float(sent)
        else:
            self._queued.append((spec.register_id, sent))
        return sent

    def apply_queued(self) -> None:
        """The device came back: queued writes become visible."""
        for register_id, value in self._queued:
            self.values[register_id] = float(value)
        self._queued.clear()


__all__ = ["FIXTURES", "INSTALLATION_ID", "FakeApi", "FakeAuth", "RegisterWriteError"]
