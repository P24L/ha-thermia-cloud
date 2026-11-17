"""Discovery of an installation's registers (cached in a HA ``Store`` by ``__init__``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .client.api import ThermiaApi
from .client.models import HistoryRegister, RegisterSpec, ValueName

REMEMBER_FOR = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class RememberedSpec:
    """A register the cloud stopped returning (e.g. the curve while a circuit is in Constant mode).

    Its entity stays, unavailable, so it is simply there again when the register returns.
    """

    spec: RegisterSpec
    last_seen: datetime


@dataclass(frozen=True, slots=True)
class Discovery:
    installation_id: int
    profile_id: int
    groups: tuple[str, ...]  # groups that returned registers (empty ones are not polled again)
    specs: tuple[RegisterSpec, ...]
    history: tuple[HistoryRegister, ...]
    fetched_at: datetime
    remembered: tuple[RememberedSpec, ...] = ()

    @property
    def all_specs(self) -> tuple[RegisterSpec, ...]:
        """Specs the cloud returns now plus the remembered ones."""
        return self.specs + tuple(r.spec for r in self.remembered)

    def to_json(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "profile_id": self.profile_id,
            "groups": list(self.groups),
            "specs": [asdict(s) for s in self.specs],
            "history": [asdict(h) for h in self.history],
            "fetched_at": self.fetched_at.isoformat(),
            "remembered": [
                {"spec": asdict(r.spec), "last_seen": r.last_seen.isoformat()}
                for r in self.remembered
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Discovery:
        specs = tuple(_spec_from_json(raw) for raw in data["specs"])
        return cls(
            installation_id=int(data["installation_id"]),
            profile_id=int(data["profile_id"]),
            groups=tuple(data["groups"]),
            specs=specs,
            history=tuple(HistoryRegister(**h) for h in data["history"]),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
            remembered=tuple(
                RememberedSpec(_spec_from_json(r["spec"]), datetime.fromisoformat(r["last_seen"]))
                for r in data.get("remembered", ())
            ),
        )

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(UTC)) - self.fetched_at).total_seconds()


def _spec_from_json(raw: dict[str, Any]) -> RegisterSpec:
    return RegisterSpec(**{**raw, "value_names": tuple(ValueName(**v) for v in raw["value_names"])})


def merge_remembered(
    previous: Discovery | None,
    fresh: Discovery,
    *,
    forget: bool = False,
    now: datetime | None = None,
) -> Discovery:
    """Carry registers that disappeared since ``previous`` over into ``fresh`` as remembered ones.

    Registers the cloud only returns in some state (circuit mode, hot water on/off) vanish and
    come back; remembering their specs keeps their entities instead of dropping and recreating
    them. They are forgotten after 30 days, or at once with ``forget`` (the *Rediscover* button).
    """
    if previous is None or forget:
        return fresh
    now = now or datetime.now(UTC)
    live = {s.register_id for s in fresh.specs}
    carried: dict[int, RememberedSpec] = {}
    for spec in previous.specs:
        if spec.register_id not in live:
            carried[spec.register_id] = RememberedSpec(spec, previous.fetched_at)
    for item in previous.remembered:
        if item.spec.register_id not in live:
            carried.setdefault(item.spec.register_id, item)
    kept = tuple(r for r in carried.values() if now - r.last_seen <= REMEMBER_FOR)
    return replace(fresh, remembered=kept)


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
