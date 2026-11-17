"""A fake ``ThermiaApi`` backed by the iTec fixtures, for integration tests."""

import json
from pathlib import Path
from typing import Any

from custom_components.thermia_cloud.client.models import (
    Group,
    HistoryRegister,
    Installation,
    InstallationDetail,
    RegisterSpec,
    RegisterValue,
)

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

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    async def list_installations(self) -> list[Installation]:
        self._check("list_installations")
        return [Installation(INSTALLATION_ID, "Test installation", "iTec", True, "1.0", None)]

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
        raw: list[dict[str, Any]] = json.loads((FIXTURES / f"group_{group_name}.json").read_text())
        out = []
        for item in raw:
            if item["registerName"] in self.hide:
                continue
            if item["registerName"] in self.overrides:
                item = {**item, "registerValue": self.overrides[item["registerName"]]}
            out.append((RegisterSpec.from_json(item), RegisterValue.from_json(item)))
        return out

    async def get_history_registers(self, installation_id: int) -> list[HistoryRegister]:
        self._check("get_history_registers")
        data = json.loads((FIXTURES / "history_registers.json").read_text())
        return [HistoryRegister.from_json(r) for r in data["registers"]]
