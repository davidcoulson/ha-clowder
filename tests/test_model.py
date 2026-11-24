"""Tests for the tracker model (no Home Assistant needed)."""

import math

from custom_components.clowder.model import Tracker, VisitRecord

DAY = 86400
T0 = 1_000_000


def ev(**kw):
    base = {
        "node": "litter-robot4-lr4c000001",
        "robot": "LR4C000001",
        "epoch": "7",
        "id": "1",
        "slot": "4",
        "name": "Luna",
        "method": "Tag",
        "rssi": "-52",
        "weight": "11.46",
        "time": str(T0),
        "age": "5",
        "waste": "pending",
        "waste_weight": "",
        "final": "0",
    }
    return base | {k: str(v) for k, v in kw.items()}


def rec(received=T0 + 10, **kw):
    r = VisitRecord.from_event(ev(**kw), received)
    assert r is not None
    return r


def test_pending_then_final_counts_once():
    t = Tracker(1.0)
    r1 = t.apply(rec(), T0 + 10)
    r2 = t.apply(rec(waste="urine", final=1), T0 + 200)
    c = t.cats[4]
    assert (r1.new_visit, r2.new_visit) == (True, False)
    assert (r1.changed, r2.changed) == (True, True)
    assert (c.visits, c.pee, c.poop, c.weight) == (1, 1, 0, 11.46)
    assert (c.name, c.last_robot, c.last_visit) == ("Luna", "LR4C000001", T0)


def test_final_without_pending_counts_visit_and_waste():
    t = Tracker(1.0)
    t.apply(rec(waste="feces", final=1), T0 + 200)
    assert (t.cats[4].visits, t.cats[4].poop, t.cats[4].pee) == (1, 1, 0)


def test_final_with_pending_waste_counts_visit_only():
    t = Tracker(1.0)
    t.apply(rec(final=1), T0 + 200)
    assert (t.cats[4].visits, t.cats[4].poop, t.cats[4].pee) == (1, 0, 0)


def test_resend_of_final_changes_nothing():
    t = Tracker(1.0)
    t.apply(rec(waste="urine", final=1), T0 + 200)
    before = t.to_dict()
    r = t.apply(rec(waste="urine", final=1), T0 + 260)
    assert (r.new_visit, r.changed) == (False, False)
    assert t.to_dict() == before


def test_implausible_weight_counts_visit_keeps_weight():
    t = Tracker(1.0)
    t.apply(rec(), T0 + 10)
    t.apply(rec(id=2, weight="5.0", time=T0 + 100), T0 + 110)
    c = t.cats[4]
    assert (c.visits, c.weight) == (2, 11.46)
    assert c.avg_weight_7d(T0 + 200) == 11.46


def test_nan_weight_counts_visit():
    t = Tracker(1.0)
    r = rec(weight="nan")
    assert math.isnan(r.weight)
    t.apply(r, T0 + 10)
    assert (t.cats[4].visits, t.cats[4].weight) == (1, None)
    assert t.cats[4].avg_weight_7d(T0 + 20) is None


def test_no_clock_uses_received_minus_age():
    assert rec(received=5000, time=0, age=60).when == 4940
    assert rec(received=5000, time=0, age=-1).when == 5000
    assert rec(received=5000).when == T0


def test_old_visit_counts_but_not_in_7d():
    now = T0 + 8 * DAY
    t = Tracker(1.0)
    t.apply(rec(received=now), now)
    c = t.cats[4]
    assert c.visits == 1
    assert c.visits_per_day_7d(now) == 0
    assert c.avg_weight_7d(now) is None


def test_7d_figures():
    t = Tracker(1.0)
    for i in range(7):
        t.apply(rec(id=i + 1, time=T0 + i * 3600, weight=str(11.0 + (i % 2))), T0 + i * 3600)
    c = t.cats[4]
    now = T0 + 7 * 3600
    assert c.visits_per_day_7d(now) == 1.0
    assert round(c.avg_weight_7d(now), 3) == round((11.0 * 4 + 12.0 * 3) / 7, 3)
    assert c.hours_since_last_visit(now) == 1.0
    assert Tracker(1.0).hello({1: "Ash"}) == [] and Tracker(1.0).cats == {}


def test_two_robots_last_robot_by_visit_time():
    t = Tracker(1.0)
    t.apply(rec(robot="B", node="b", time=T0 + 50), T0 + 60)
    t.apply(rec(robot="A", node="a", time=T0 + 20), T0 + 70)  # earlier visit, arrives later
    c = t.cats[4]
    assert (c.visits, c.last_robot, c.last_visit) == (2, "B", T0 + 50)


def test_junk_event_returns_none():
    for bad in (
        ev(slot=9),
        ev(slot=-1),
        ev(waste="maybe"),
        ev(epoch="x"),
        ev(id=""),
        ev(robot=""),
        ev(node=""),
        {k: v for k, v in ev().items() if k != "epoch"},
        {},
    ):
        assert VisitRecord.from_event(bad, T0) is None


def test_optional_fields_default():
    data = {k: v for k, v in ev().items() if k in ("node", "robot", "epoch", "id", "slot", "waste")}
    r = VisitRecord.from_event(data, T0)
    assert r is not None
    assert (r.when, r.final, r.waste_weight, r.rssi) == (T0, False, None, 0)
    assert math.isnan(r.weight)
    assert rec(final="true").final is True
    assert rec(waste_weight="junk").waste_weight is None


def test_unidentified_never_touches_cats():
    t = Tracker(1.0)
    r1 = t.apply(rec(slot=0, name="Unknown"), T0 + 10)
    r2 = t.apply(rec(slot=0, name="Unknown", final=1, waste="urine"), T0 + 200)
    assert t.cats == {}
    assert (r1.unidentified, r1.new_visit, r2.unidentified, r2.new_visit) == (
        True,
        True,
        True,
        False,
    )


def test_waste_weight_sets_value():
    t = Tracker(1.0)
    t.apply(rec(waste="feces", final=1), T0 + 200)
    r = t.apply(rec(waste="feces", final=1, waste_weight="0.08"), T0 + 900)
    assert r.changed
    assert (t.cats[4].poop, t.cats[4].poop_weight, t.cats[4].pee_weight) == (1, 0.08, None)
    assert not t.apply(rec(waste="feces", final=1, waste_weight="0.08"), T0 + 960).changed
    t.apply(rec(id=2, time=T0 + 5, waste="urine", final=1, waste_weight="0.05"), T0 + 900)
    assert t.cats[4].pee_weight == 0.05


def test_update_before_reset_ignored():
    t = Tracker(1.0)
    t.apply(rec(), T0 + 10)
    t.reset(4, T0 + 100)
    c = t.cats[4]
    assert (c.visits, c.weight, c.last_visit, c.last_robot, c.log) == (0, None, None, None, [])
    r = t.apply(rec(waste="feces", final=1), T0 + 200)
    assert not r.changed
    assert (c.visits, c.poop) == (0, 0)
    t.apply(rec(id=2, time=T0 + 150), T0 + 160)
    assert c.visits == 1


def test_set_weight():
    t = Tracker(1.0)
    t.hello({4: "Luna"})
    t.set_weight(4, 12.5)
    assert t.cats[4].weight == 12.5
    t.apply(rec(), T0 + 10)  # 11.46 is more than 1.0 from 12.5
    assert t.cats[4].weight == 12.5


def test_hello_creates_and_reports_conflicts():
    t = Tracker(1.0)
    assert t.hello({1: "Ash", 4: "Luna"}) == []
    assert t.hello({1: "Ash", 4: "Nori"}) == [4]
    assert t.cats[4].name == "Luna"
    assert sorted(t.cats) == [1, 4]


def test_dedupe_memory_keeps_64_per_robot():
    t = Tracker(1.0)
    for i in range(1, 66):
        t.apply(rec(id=i, time=T0 + i), T0 + i)
    t.apply(rec(robot="OTHER", node="o", time=T0 + 70), T0 + 70)
    assert t.cats[4].visits == 66
    assert t.apply(rec(id=65, time=T0 + 65), T0 + 80).new_visit is False
    assert t.apply(rec(id=1, time=T0 + 1), T0 + 90).new_visit is True  # forgotten: oldest of 65


def test_log_pruned_to_window():
    t = Tracker(1.0)
    t.apply(rec(), T0 + 10)
    t.apply(rec(id=2, time=T0 + 8 * DAY), T0 + 8 * DAY)
    assert len(t.cats[4].log) == 1


def test_roundtrip():
    t = Tracker(1.0)
    t.hello({1: "Ash"})
    t.apply(rec(), T0 + 10)
    t.apply(rec(waste="feces", final=1, waste_weight="0.1"), T0 + 200)
    t.apply(rec(slot=0, id=2), T0 + 300)
    t.reset(1, T0 + 400)
    d = t.to_dict()
    import json

    t2 = Tracker.from_dict(json.loads(json.dumps(d)), 1.0)
    assert t2.to_dict() == d
    assert t2.apply(rec(waste="feces", final=1), T0 + 500).changed is False
    assert Tracker.from_dict({}, 2.0).cats == {}


def test_rollup_survives_storage_and_forgets_old_visits():
    tracker = Tracker(3.0)
    tracker.apply(VisitRecord.from_event(ev(), T0), T0)
    tracker.apply(VisitRecord.from_event(ev(id=2, slot=0, name="Unknown"), T0), T0)
    restored = Tracker.from_dict(tracker.to_dict(), 3.0)
    assert restored.unidentified == 1
    assert restored.last == (T0, "Unknown", "LR4C000001")
    assert restored.visits_since(T0 - 60) == 2
    later = T0 + 3 * 86400
    restored.apply(VisitRecord.from_event(ev(id=3, time=later), later), later)
    assert restored.recent == [later]
    assert Tracker.from_dict({}, 3.0).last is None
