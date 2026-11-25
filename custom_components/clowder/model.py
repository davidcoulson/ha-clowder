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
# A robot's clock is believed only this far behind or ahead of Home Assistant's.
CLOCK_BEHIND_S = 30 * 86400
CLOCK_AHEAD_S = 300
# A cat back on a robot within this long of its last visit is still on the same visit.
MERGE_S = 300


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
        if time > 0 and received - CLOCK_BEHIND_S <= time <= received + CLOCK_AHEAD_S:
            when = float(time)
        elif 0 <= age <= CLOCK_BEHIND_S:
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
    # The visit in progress: first and last weight report, and the waste counted for it.
    sit_start: float | None = None
    sit_last: float | None = None
    sit_waste: str | None = None
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
        # robot -> {(epoch, id): (waste already counted, time of the first copy)}, oldest first
        self._seen: dict[str, dict[tuple[int, int], tuple[bool, float | None]]] = {}
        # Rollup across all cats, unidentified visits included.
        self.recent: list[float] = []  # visit times, last 2 days
        self.unidentified = 0
        self.last: tuple[float, str, str] | None = None  # (time, cat name, robot)

    def _roll(self, rec: VisitRecord, name: str, now: float, count: bool = True) -> None:
        if count:
            self.recent = [t for t in self.recent if t > now - 2 * 86400] + [rec.when]
        if self.last is None or rec.when >= self.last[0]:
            self.last = (rec.when, name, rec.robot)

    def visits_since(self, start: float) -> int:
        return sum(1 for t in self.recent if t >= start)

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
        counted, first = seen.get(ident, (False, None))
        # Every copy of a visit gets the first copy's time: a later one may have no clock.
        when = rec.when if first is None else first
        final_new = rec.final and not counted
        if new_visit or final_new:
            seen[ident] = (rec.final, when)
            while len(seen) > DEDUPE_KEYS:
                del seen[next(iter(seen))]

        if rec.slot == 0:
            if new_visit:
                self.unidentified += 1
                self._roll(rec, "Unknown", now)
            return ApplyResult(0, new_visit, new_visit, True)

        cat = self.cats.setdefault(rec.slot, CatState(rec.slot, rec.name))
        if when < cat.reset_at:
            return ApplyResult(rec.slot, False, False, False)

        changed = False
        # A visit delivered late must not replace what a newer visit set.
        newest = cat.last_visit is None or when >= cat.last_visit
        if new_visit:
            changed = True
            # Stepping out and back in, or over to the next robot, sends a report each time.
            merged = (
                cat.sit_last is not None
                and cat.sit_start - MERGE_S <= when <= cat.sit_last + MERGE_S
            )
            if merged:
                cat.sit_start = min(cat.sit_start, when)
                cat.sit_last = max(cat.sit_last, when)
            elif newest:
                cat.sit_start = cat.sit_last = when
                cat.sit_waste = None
            if not merged:
                cat.visits += 1
            self._roll(rec, cat.name, now, count=not merged)
            plausible = not math.isnan(rec.weight) and (
                cat.weight is None or abs(rec.weight - cat.weight) <= self.max_weight_jump
            )
            if plausible and newest:
                cat.weight = rec.weight
            if not merged:
                cat.log.append((rec.when, rec.weight if plausible else None))
            if newest:
                cat.last_visit = rec.when
                cat.last_robot = rec.robot
        if final_new and rec.waste != "pending":
            in_sit = cat.sit_last is not None and cat.sit_start <= when <= cat.sit_last
            counted_as = cat.sit_waste if in_sit else None
            # One result per visit. Feces wins: a robot calls an interrupted stop urine.
            if counted_as is None or (counted_as, rec.waste) == ("urine", "feces"):
                if counted_as:
                    cat.pee -= 1
                if rec.waste == "feces":
                    cat.poop += 1
                else:
                    cat.pee += 1
                if in_sit:
                    cat.sit_waste = rec.waste
                changed = True
        if rec.waste_weight is not None and rec.waste != "pending" and newest:
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
                    "sit_start": c.sit_start,
                    "sit_last": c.sit_last,
                    "sit_waste": c.sit_waste,
                    "log": [list(e) for e in c.log],
                }
                for slot, c in self.cats.items()
            },
            "seen": {
                robot: [[epoch, rec_id, *value] for (epoch, rec_id), value in keys.items()]
                for robot, keys in self._seen.items()
            },
            "rollup": {
                "recent": self.recent,
                "unidentified": self.unidentified,
                "last": list(self.last) if self.last else None,
            },
        }

    @classmethod
    def from_dict(cls, data: dict, max_weight_jump: float) -> Tracker:
        tracker = cls(max_weight_jump)
        for slot, c in data.get("cats", {}).items():
            fields = {**c, "log": [(e[0], e[1]) for e in c.get("log", [])]}
            tracker.cats[int(slot)] = CatState(slot=int(slot), **fields)
        for robot, keys in data.get("seen", {}).items():
            tracker._seen[robot] = {
                (k[0], k[1]): (bool(k[2]), k[3] if len(k) > 3 else None) for k in keys
            }
        rollup = data.get("rollup", {})
        tracker.recent = list(rollup.get("recent", []))
        tracker.unidentified = rollup.get("unidentified", 0)
        tracker.last = tuple(rollup["last"]) if rollup.get("last") else None
        return tracker
