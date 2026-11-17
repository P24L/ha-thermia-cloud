"""Discovery of an installation's registers (cached in a HA ``Store`` by ``__init__``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .client.api import ThermiaApi
from .client.models import HistoryRegister, RegisterSpec, ValueName


@dataclass(frozen=True, slots=True)
class Discovery:
    installation_id: int
    profile_id: int
    groups: tuple[str, ...]  # groups that returned registers (empty ones are not polled again)
    specs: tuple[RegisterSpec, ...]
    history: tuple[HistoryRegister, ...]
    fetched_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "profile_id": self.profile_id,
            "groups": list(self.groups),
            "specs": [asdict(s) for s in self.specs],
            "history": [asdict(h) for h in self.history],
            "fetched_at": self.fetched_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Discovery:
        specs = tuple(
            RegisterSpec(
                **{
                    **raw,
                    "value_names": tuple(ValueName(**v) for v in raw["value_names"]),
                }
            )
            for raw in data["specs"]
        )
        return cls(
            installation_id=int(data["installation_id"]),
            profile_id=int(data["profile_id"]),
            groups=tuple(data["groups"]),
            specs=specs,
            history=tuple(HistoryRegister(**h) for h in data["history"]),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(UTC)) - self.fetched_at).total_seconds()


async def discover(api: ThermiaApi, installation_id: int) -> Discovery:
    """Read the profile's groups, every group's registers and the history metadata."""
    detail = await api.get_installation(installation_id)
    groups = await api.get_groups(detail.profile_id)
    live: list[str] = []
    specs: list[RegisterSpec] = []
    for group in groups:
        registers = await api.get_group_registers(installation_id, group.name)
        if registers:
            live.append(group.name)
            specs.extend(spec for spec, _ in registers)
    history = await api.get_history_registers(installation_id)
    return Discovery(
        installation_id, detail.profile_id, tuple(live), tuple(specs), tuple(history),
        datetime.now(UTC),
    )  # fmt: skip
