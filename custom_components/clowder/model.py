"""Per-cat visit counting. No Home Assistant imports: this is the only place the rules live."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .const import DEDUPE_KEYS, MAX_SLOT, WINDOW_S

_LOGGER = logging.getLogger(__name__)

WASTE_VALUES = ("pending", "feces", "urine")


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class VisitRecord:
    """One visit as a robot reported it. Event data arrive as strings."""

    node: str
    robot: str
    epoch: int
    id: int
    slot: int
    name: str
    method: str
    rssi: int
    weight: float  # lb, nan when the robot sent nothing usable
    when: float  # epoch seconds of the visit
    waste: str
    waste_weight: float | None
    final: bool

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.robot, self.epoch, self.id)

    @classmethod
    def from_event(cls, data: Mapping[str, Any], received: float) -> VisitRecord | None:
        node = str(data.get("node", "")).strip()
        robot = str(data.get("robot", "")).strip()
        epoch = _int(data.get("epoch"))
        rec_id = _int(data.get("id"))
        slot = _int(data.get("slot"))
        waste = str(data.get("waste", "")).strip().lower()
        if (
            not node
            or not robot
            or epoch is None
            or rec_id is None
            or slot is None
            or not 0 <= slot <= MAX_SLOT
            or waste not in WASTE_VALUES
        ):
            _LOGGER.warning("Ignoring malformed visit event: %s", dict(data))
            return None
        weight = _float(data.get("weight"))
        time = _int(data.get("time"), 0)
        age = _int(data.get("age"), -1)
        if time > 0:
            when = float(time)
        elif age >= 0:
            when = received - age
        else:
            when = received
        return cls(
            node=node,
            robot=robot,
            epoch=epoch,
            id=rec_id,
            slot=slot,
            name=str(data.get("name", "")).strip() or f"Cat {slot}",
            method=str(data.get("method", "")).strip(),
            rssi=_int(data.get("rssi"), 0),
            weight=weight if weight is not None and weight > 0 else math.nan,
            when=when,
            waste=waste,
            waste_weight=_float(data.get("waste_weight")),
            final=str(data.get("final", "")).strip().lower() in ("1", "true"),
        )


@dataclass
class CatState:
    """Everything known about one cat."""

    slot: int
    name: str
    weight: float | None = None
    visits: int = 0
    poop: int = 0
    pee: int = 0
    poop_weight: float | None = None
    pee_weight: float | None = None
    last_visit: float | None = None
    last_robot: str | None = None
    reset_at: float = 0.0
    # (visit time, plausible weight or None), last 7 days only
    log: list[tuple[float, float | None]] = field(default_factory=list)

    def _recent(self, now: float) -> list[tuple[float, float | None]]:
        return [e for e in self.log if now - WINDOW_S < e[0] <= now]

    def avg_weight_7d(self, now: float) -> float | None:
        weights = [w for _, w in self._recent(now) if w is not None]
        return sum(weights) / len(weights) if weights else None

    def visits_per_day_7d(self, now: float) -> float:
        return len(self._recent(now)) / 7

    def hours_since_last_visit(self, now: float) -> float | None:
        if self.last_visit is None:
            return None
        return max(0.0, now - self.last_visit) / 3600


@dataclass(frozen=True)
class ApplyResult:
    slot: int
    new_visit: bool
    changed: bool
    unidentified: bool


class Tracker:
    """Applies visit records to cats, counting each (robot, epoch, id) once."""

    def __init__(self, max_weight_jump: float) -> None:
        self.max_weight_jump = max_weight_jump
        self.cats: dict[int, CatState] = {}
        # robot -> {(epoch, id): waste already counted}, oldest first
        self._seen: dict[str, dict[tuple[int, int], bool]] = {}

    def hello(self, cats: dict[int, str]) -> list[int]:
        """Add unknown cats; return slots whose name differs from the stored one."""
        conflicts = []
        for slot, name in cats.items():
            if slot not in self.cats:
                self.cats[slot] = CatState(slot, name)
            elif self.cats[slot].name != name:
                conflicts.append(slot)
        return conflicts

    def apply(self, rec: VisitRecord, now: float) -> ApplyResult:
        seen = self._seen.setdefault(rec.robot, {})
        ident = (rec.epoch, rec.id)
        new_visit = ident not in seen
        final_new = rec.final and not seen.get(ident, False)
        if new_visit or final_new:
            seen[ident] = rec.final
            while len(seen) > DEDUPE_KEYS:
                del seen[next(iter(seen))]

        if rec.slot == 0:
            return ApplyResult(0, new_visit, new_visit, True)

        cat = self.cats.setdefault(rec.slot, CatState(rec.slot, rec.name))
        if rec.when < cat.reset_at:
            return ApplyResult(rec.slot, False, False, False)

        changed = False
        if new_visit:
            changed = True
            cat.visits += 1
            plausible = not math.isnan(rec.weight) and (
                cat.weight is None or abs(rec.weight - cat.weight) <= self.max_weight_jump
            )
            if plausible:
                cat.weight = rec.weight
            cat.log.append((rec.when, rec.weight if plausible else None))
            if cat.last_visit is None or rec.when > cat.last_visit:
                cat.last_visit = rec.when
                cat.last_robot = rec.robot
        if final_new and rec.waste == "feces":
            cat.poop += 1
            changed = True
        elif final_new and rec.waste == "urine":
            cat.pee += 1
            changed = True
        if rec.waste_weight is not None and rec.waste != "pending":
            attr = "poop_weight" if rec.waste == "feces" else "pee_weight"
            if getattr(cat, attr) != rec.waste_weight:
                setattr(cat, attr, rec.waste_weight)
                changed = True
        if changed:
            cat.log = [e for e in cat.log if e[0] > now - WINDOW_S]
        return ApplyResult(rec.slot, new_visit, changed, False)

    def reset(self, slot: int, now: float) -> None:
        old = self.cats[slot]
        self.cats[slot] = CatState(slot, old.name, reset_at=now)

    def set_weight(self, slot: int, weight: float) -> None:
        self.cats[slot].weight = weight

    def to_dict(self) -> dict:
        return {
            "cats": {
                str(slot): {
                    "name": c.name,
                    "weight": c.weight,
                    "visits": c.visits,
                    "poop": c.poop,
                    "pee": c.pee,
                    "poop_weight": c.poop_weight,
                    "pee_weight": c.pee_weight,
                    "last_visit": c.last_visit,
                    "last_robot": c.last_robot,
                    "reset_at": c.reset_at,
                    "log": [list(e) for e in c.log],
                }
                for slot, c in self.cats.items()
            },
            "seen": {
                robot: [[epoch, rec_id, counted] for (epoch, rec_id), counted in keys.items()]
                for robot, keys in self._seen.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict, max_weight_jump: float) -> Tracker:
        tracker = cls(max_weight_jump)
        for slot, c in data.get("cats", {}).items():
            fields = {**c, "log": [(e[0], e[1]) for e in c.get("log", [])]}
            tracker.cats[int(slot)] = CatState(slot=int(slot), **fields)
        for robot, keys in data.get("seen", {}).items():
            tracker._seen[robot] = {(k[0], k[1]): bool(k[2]) for k in keys}
        return tracker
