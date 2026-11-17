"""Pure entity planner: ``(specs, values, catalog, options) -> EntityPlan``s.

No Home Assistant imports. Rules: ``docs/ARCHITECTURE.md`` section 4 and ``docs/CATALOG.md``.
Names are not resolved here (labels are the ``LabelResolver``'s job); a plan carries the keys.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..client.models import HistoryRegister, RegisterSpec, RegisterValue, ValueName
from ..client.visibility import (
    RegisterLookup,
    VisibilityParseError,
    evaluate_node,
    node_to_text,
    parse_condition,
)
from .schema import Catalog, CatalogRegister, Kind, Risk
from .units import HOURS_MODIFIER, TEMPERATURE_MODIFIERS, resolve_unit

MAX_DISPLAY_DECIMALS = 2
INDOOR_TEMPERATURE_REGISTER = "REG_INDOOR_TEMPERATURE"
STATUS_FLAG_PRESENTATIONS = frozenset({"StatusFlags", "StatusFlagsTextInd", "MultipleStatusFlags"})
SLIDER_MAX_STEPS = 100


_OPTION_PREFIX = re.compile(r"^REG_VALUE_(?:STATUS_|OPERATION_MODE_|MODE_)?")


def option_key(name: str) -> str:
    """Stable select/enum option id from a cloud value name.

    ``REG_VALUE_OPERATION_MODE_HOT_WATER`` -> ``hot_water``, ``Comfort`` -> ``comfort``. The
    result is language independent, so automations survive a change of language.
    """
    return _OPTION_PREFIX.sub("", name).strip().lower().replace(" ", "_").replace(".", "")


@dataclass(frozen=True, slots=True)
class PlannerOptions:
    show_hidden: bool = False  # create entities whose structural visibility is false
    expose_unknown: bool = True  # generic (disabled) entities for registers the catalog lacks
    # From the installation status (``hasIndoorTempSensor``): False means the pump has no indoor
    # sensor, so its indoor-temperature register only holds a stale leftover and gets no entity.
    has_indoor_sensor: bool | None = None
    stale_after: timedelta = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class EntityPlan:
    platform: str  # sensor | binary_sensor | number | select | switch
    key: str  # unique-id part (D10): registerIndex, plus "_<flag>" for status flags
    register_id: int  # write id; the key uses register_index instead
    register_index: int
    register_name: str
    group_name: str
    device: str
    label_key: str  # cloud key to label this entity (register name / flag value name)
    translation_key: str | None
    description_key: str | None
    unit: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    icon: str | None
    default_enabled: bool
    stale: bool
    risk: str
    writable: bool
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    number_mode: str | None = None  # slider | box
    options: tuple[tuple[int, str], ...] = ()  # visible enum values (value, cloud name)
    flag_value: int | None = None
    flag_equality: bool = False  # True: flag == value; False: bitmask (value & flag == flag)
    display_precision: int | None = None
    runtime_condition: str | None = None  # value-based visibility: false -> unavailable
    disabled_value: float | None = None  # register value meaning "sensor not connected"
    state_dependent: bool = False  # the cloud only returns it in some state (mode, hot water on)


@dataclass(frozen=True, slots=True)
class PlanNote:
    code: str
    register: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Plan:
    entities: tuple[EntityPlan, ...]
    notes: tuple[PlanNote, ...]


def _visible_options(spec: RegisterSpec) -> tuple[ValueName, ...]:
    """Visible value names, one per value (*visible wins* over hidden duplicates)."""
    seen: dict[int, ValueName] = {}
    for value_name in spec.value_names:
        if value_name.visible and value_name.value not in seen:
            seen[value_name.value] = value_name
    return tuple(seen.values())


def _generic_platform(spec: RegisterSpec, notes: list[PlanNote]) -> str | None:
    if spec.presentation == "Hidden" or spec.is_invisible:
        return None
    if spec.presentation in STATUS_FLAG_PRESENTATIONS:
        return "binary_sensor"
    if spec.presentation == "PosixTime":
        return "sensor"
    if spec.presentation == "Enumeration":
        if spec.is_read_only:
            return "sensor"
        values = {v.value for v in _visible_options(spec)}
        return "switch" if values == {0, 1} else "select"
    if spec.presentation in ("Integer", "Slider"):
        if spec.is_read_only:
            return "sensor"
        if spec.min_value is None or spec.max_value is None:
            notes.append(PlanNote("writable_without_limits", spec.name, spec.presentation))
            return None
        return "number"
    notes.append(PlanNote("unknown_presentation", spec.name, spec.presentation))
    return None


def _decimals(step: float | None) -> int | None:
    if step is None or step <= 0:
        return None
    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    # a step like 0.0167 (1/60) must not give four displayed decimals
    return min(MAX_DISPLAY_DECIMALS, max(0, -int(exponent))) if isinstance(exponent, int) else None


def _choose_platform(
    spec: RegisterSpec, entry: CatalogRegister | None, notes: list[PlanNote]
) -> str | None:
    generic = _generic_platform(spec, notes)
    if generic is None:
        return None
    if entry is None:
        return generic
    if entry.kind is Kind.SKIP:
        return None
    wanted = entry.kind.value
    if wanted == generic:
        return generic
    compatible = {
        "sensor": True,
        "binary_sensor": generic == "binary_sensor",
        "number": generic == "number",
        "select": generic in ("select", "switch"),
        "switch": generic == "switch",
    }[wanted]
    if compatible:
        return wanted
    notes.append(PlanNote("catalog_kind_incompatible", spec.name, f"{wanted} vs {generic}"))
    return generic


def effective_risk(spec: RegisterSpec, entry: CatalogRegister | None) -> Risk:
    if entry is not None and entry.risk is not Risk.NONE:
        return entry.risk
    if entry is None and spec.name.startswith("REG_SER_"):
        return Risk.SERVICE
    return Risk.NONE


def build_plan(
    registers: Sequence[tuple[RegisterSpec, RegisterValue]],
    catalog: Catalog,
    *,
    history: Mapping[int, HistoryRegister] | None = None,
    options: PlannerOptions = PlannerOptions(),
    now: datetime,
    en_labels: Mapping[str, str] | None = None,
) -> Plan:
    """``now`` must be comparable to the (zone-less) register timestamps."""
    history = history or {}
    en_labels = en_labels or {}
    notes: list[PlanNote] = []
    entities: list[EntityPlan] = []
    lookup = RegisterLookup((s.group_name, s.name, v.value) for s, v in registers)

    for spec, value in registers:
        if spec.name == INDOOR_TEMPERATURE_REGISTER and options.has_indoor_sensor is False:
            notes.append(PlanNote("no_indoor_sensor", spec.name))
            continue
        entry = catalog.lookup(spec.group_name, spec.name)
        if entry is None and not options.expose_unknown:
            notes.append(PlanNote("unknown_register_hidden", spec.name, spec.group_name))
            continue
        platform = _choose_platform(spec, entry, notes)
        if platform is None:
            continue

        # -- visibility: structural at discovery, value-based kept for runtime ----------------
        runtime_condition: str | None = None
        disabled_value: float | None = None
        meta = history.get(spec.register_index)
        if meta is not None:
            disabled_value = meta.disabled_register_value
            if meta.visibility_condition:
                try:
                    condition = parse_condition(meta.visibility_condition)
                except VisibilityParseError as err:
                    notes.append(PlanNote("condition_unparsable", spec.name, str(err)))
                else:
                    structural, runtime = condition.split(spec.name)
                    result = evaluate_node(structural, lookup.resolver(spec.group_name))
                    for name in sorted(result.unresolved):
                        notes.append(PlanNote("unresolved_reference", spec.name, name))
                    if not result.visible and not options.show_hidden:
                        notes.append(PlanNote("hidden_by_condition", spec.name, condition.text))
                        continue
                    runtime_condition = node_to_text(runtime) if runtime is not None else None

        risk = effective_risk(spec, entry)
        writable_kind = platform in ("number", "select", "switch")
        if writable_kind and risk is Risk.SERVICE:
            notes.append(PlanNote("service_register_read_only", spec.name))
            platform = "sensor"

        # Only measured values go stale: a setting's timestamp is its last *change*, which can
        # be years ago on a perfectly healthy register (e.g. a hot-water mode set in 2024).
        stale = (
            platform in ("sensor", "binary_sensor")
            and value.timestamp is not None
            and now - value.timestamp > options.stale_after
        )
        enabled = bool(entry and entry.default_enabled) and not stale
        category = catalog.category_for(spec.group_name, entry)
        unit = resolve_unit(entry.unit if entry else None, spec.modifier, en_labels.get(spec.name))
        device_class = entry.device_class if entry else None
        state_class = entry.state_class if entry else None
        if state_class is None and platform == "sensor":
            if spec.modifier in TEMPERATURE_MODIFIERS:
                state_class = "measurement"
            elif spec.modifier == HOURS_MODIFIER:
                state_class = "total_increasing"

        common = {
            "register_id": spec.register_id,
            "register_index": spec.register_index,
            "register_name": spec.name,
            "group_name": spec.group_name,
            "device": catalog.device_for(spec.group_name, entry),
            "translation_key": entry.translation_key if entry else None,
            "description_key": entry.description_key if entry else None,
            "entity_category": category.value if category else None,
            "icon": entry.icon if entry else None,
            "default_enabled": enabled,
            "stale": stale,
            "risk": risk.value,
            "runtime_condition": runtime_condition,
            "disabled_value": disabled_value,
            "state_dependent": bool(entry and entry.state_dependent),
        }

        if platform == "binary_sensor":
            visible = _visible_options(spec)
            visible_values = {v.value for v in visible}
            hidden = {
                v.value: v
                for v in spec.value_names
                if not v.visible and v.value not in visible_values
            }
            # Visible flags follow the catalog. Flags the cloud hides (e.g. the heating circuit
            # pump) are still real signals worth a history: offered as disabled diagnostics.
            flags = [(f, False) for f in visible] + [(f, True) for f in hidden.values()]
            for flag, is_hidden in flags:
                flag_common = dict(common)
                if is_hidden:
                    flag_common.update(default_enabled=False, entity_category="diagnostic")
                entities.append(
                    EntityPlan(
                        platform="binary_sensor",
                        key=f"{spec.register_index}_{flag.value}",
                        label_key=flag.name,
                        unit=None,
                        device_class=device_class,
                        state_class=None,
                        writable=False,
                        flag_value=flag.value,
                        flag_equality=spec.presentation == "StatusFlags",
                        **flag_common,  # type: ignore[arg-type]
                    )
                )
            continue

        options_list = tuple((v.value, v.name) for v in _visible_options(spec))
        plan_kwargs: dict[str, object] = {}
        if platform == "number":
            step = spec.step or 1.0
            assert spec.min_value is not None and spec.max_value is not None
            steps = (spec.max_value - spec.min_value) / step
            plan_kwargs.update(
                min_value=spec.min_value,
                max_value=spec.max_value,
                step=step,
                number_mode="slider" if steps <= SLIDER_MAX_STEPS else "box",
            )
        elif platform in ("select", "switch"):
            plan_kwargs["options"] = options_list
        elif platform == "sensor":
            if spec.presentation == "PosixTime":
                device_class = "timestamp"
            elif spec.presentation == "Enumeration":
                device_class = device_class or "enum"
                plan_kwargs["options"] = options_list
            plan_kwargs["display_precision"] = _decimals(spec.step)

        entities.append(
            EntityPlan(
                platform=platform,
                key=str(spec.register_index),
                label_key=spec.name,
                unit=None if spec.presentation in ("Enumeration", "PosixTime") else unit,
                device_class=device_class,
                state_class=state_class,
                writable=platform in ("number", "select", "switch"),
                **plan_kwargs,  # type: ignore[arg-type]
                **common,  # type: ignore[arg-type]
            )
        )
    return Plan(tuple(entities), tuple(notes))


def resolve_name_collisions(
    plans: Sequence[EntityPlan],
    label: Callable[[EntityPlan], str],
    suffix: Callable[[EntityPlan], str] = lambda p: p.group_name,
) -> dict[str, str]:
    """Map ``plan.key -> display name``; colliding names on one device get ``(suffix)``."""
    names = {p.key: label(p) for p in plans}
    by_name: dict[tuple[str, str], list[EntityPlan]] = {}
    for plan in plans:
        by_name.setdefault((plan.device, names[plan.key]), []).append(plan)
    result = dict(names)
    for (_, name), group in by_name.items():
        if len(group) > 1:
            for plan in group:
                extra = suffix(plan)
                if extra.strip().casefold() == name.strip().casefold():
                    extra = plan.platform.replace("_", " ")  # the group says the same as the name
                result[plan.key] = f"{name} ({extra})"
    return result
