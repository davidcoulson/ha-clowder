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


def rec(received=None, **kw):
    if received is None:
        received = int(kw.get("time", T0)) + 10
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
    t.apply(rec(id=2, weight="5.0", time=T0 + 3600), T0 + 3610)
    c = t.cats[4]
    assert (c.visits, c.weight) == (2, 11.46)
    assert c.avg_weight_7d(T0 + 3700) == 11.46


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
    t.apply(rec(robot="B", node="b", time=T0 + 3600), T0 + 3610)
    t.apply(rec(robot="A", node="a", time=T0 + 20), T0 + 3620)  # earlier visit, arrives later
    c = t.cats[4]
    assert (c.visits, c.last_robot, c.last_visit) == (2, "B", T0 + 3600)


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
        t.apply(rec(id=i, time=T0 + i * 600), T0 + i * 600)
    t.apply(rec(robot="OTHER", node="o", time=T0 + 70), T0 + 66 * 600)
    assert t.cats[4].visits == 66
    assert t.apply(rec(id=65, time=T0 + 65 * 600), T0 + 67 * 600).new_visit is False
    assert (
        t.apply(rec(id=1, time=T0 + 600), T0 + 68 * 600).new_visit is True
    )  # forgotten: oldest of 65


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


def test_wrong_robot_clock_falls_back_to_age_then_arrival():
    assert rec(received=T0 + 10).when == T0
    assert rec(received=T0 + 10, time=T0 + 3600).when == T0 + 5  # clock ahead: use age
    assert rec(received=T0 + 10, time=T0 - 40 * DAY).when == T0 + 5  # absurdly old
    assert rec(received=T0 + 10, time=T0 + 3600, age=-1).when == T0 + 10
    assert rec(received=T0 + 10, time=0, age=99 * DAY).when == T0 + 10
    assert rec(received=T0 + 10, time=T0 - 2 * DAY).when == T0 - 2 * DAY  # queued while HA was down


def test_final_after_reset_without_a_clock_counts_nothing():
    t = Tracker(1.0)
    t.apply(rec(time=0, age=5, received=T0), T0)
    t.reset(4, T0 + 100)
    r = t.apply(rec(time=0, age=-1, received=T0 + 200, waste="urine", final=1), T0 + 200)
    c = t.cats[4]
    assert (c.visits, c.pee, r.changed) == (0, 0, False)
    # The first copy's time survives a restart.
    t2 = Tracker.from_dict(t.to_dict(), 1.0)
    t2.apply(rec(time=0, age=-1, received=T0 + 300, waste="urine", final=1), T0 + 300)
    assert t2.cats[4].pee == 0


def test_seen_from_0_2_0_storage_loads():
    t = Tracker.from_dict({"seen": {"LR4C000001": [[7, 1, False]]}}, 1.0)
    r = t.apply(rec(waste="urine", final=1), T0 + 200)
    assert (r.new_visit, t.cats[4].pee) == (False, 1)


def test_late_older_visit_does_not_replace_newer_weights():
    t = Tracker(5.0)
    late = T0 + 3600
    t.apply(rec(robot="B", node="b", time=late, weight="12.0"), late + 10)
    t.apply(
        rec(robot="B", node="b", time=late, waste="urine", final=1, waste_weight="0.2"),
        late + 11,
    )
    t.apply(rec(robot="A", node="a", time=T0 + 20, weight="10.0"), late + 20)
    t.apply(
        rec(robot="A", node="a", time=T0 + 20, waste="urine", final=1, waste_weight="0.1"),
        late + 21,
    )
    c = t.cats[4]
    assert (c.visits, c.pee, c.weight, c.pee_weight) == (2, 2, 12.0, 0.2)
    assert c.avg_weight_7d(late + 30) == 11.0


def test_hopping_between_robots_is_one_visit():
    # One cat, two robots, five weight reports in three minutes; each re-entry closed the
    # stop before it as urine.
    t = Tracker(3.0)
    stops = [("B", 0, "11.55"), ("B", 80, "11.52"), ("A", 130, "11.59"), ("B", 147, "11.53")]
    for i, (robot, at, weight) in enumerate(stops):
        kw = {"robot": robot, "node": robot.lower(), "id": i + 1, "time": T0 + at}
        r = t.apply(rec(weight=weight, **kw), T0 + at)
        assert r.changed
        t.apply(rec(weight=weight, waste="urine", final=1, **kw), T0 + at + 20)
    c = t.cats[4]
    assert (c.visits, c.pee, c.poop) == (1, 1, 0)
    assert (c.weight, c.last_robot, c.last_visit) == (11.53, "B", T0 + 147)
    assert (len(c.log), t.visits_since(T0 - 1)) == (1, 1)
    assert t.last == (T0 + 147, "Luna", "B")
    # The real verdict for the last stop replaces the urine the robots assumed.
    t.apply(rec(robot="A", node="a", id=9, time=T0 + 171, waste="feces", final=1), T0 + 400)
    assert (c.visits, c.pee, c.poop) == (1, 0, 1)
    t.apply(rec(robot="A", node="a", id=10, time=T0 + 200, waste="urine", final=1), T0 + 410)
    assert (c.visits, c.pee, c.poop) == (1, 0, 1)
    # The merged visit survives a restart, and a visit after the gap is a new one.
    t2 = Tracker.from_dict(t.to_dict(), 3.0)
    t2.apply(rec(id=11, time=T0 + 250, waste="urine", final=1), T0 + 420)
    t2.apply(rec(id=12, time=T0 + 250 + 301, waste="urine", final=1), T0 + 900)
    c2 = t2.cats[4]
    assert (c2.visits, c2.pee, c2.poop) == (2, 1, 1)


def test_late_verdicts_find_their_own_visit():
    # Two stops on one trip, then a new trip before either verdict is in.
    t = Tracker(3.0)
    t.apply(rec(id=1, time=T0), T0)
    t.apply(rec(id=2, time=T0 + 100), T0 + 100)
    t.apply(rec(id=3, time=T0 + 500), T0 + 500)
    t.apply(rec(id=1, time=T0, waste="urine", final=1), T0 + 600)
    t.apply(rec(id=2, time=T0 + 100, waste="feces", final=1), T0 + 610)
    t.apply(rec(id=3, time=T0 + 500, waste="urine", final=1), T0 + 620)
    c = t.cats[4]
    assert (c.visits, c.pee, c.poop) == (2, 1, 1)


def test_late_reports_of_an_older_trip_are_one_visit():
    t = Tracker(3.0)
    for i, at in enumerate((600, 0, 100)):
        t.apply(rec(id=i + 1, time=T0 + at, waste="urine", final=1), T0 + 700)
    c = t.cats[4]
    assert (c.visits, c.pee, len(c.log)) == (2, 2, 2)
    assert c.last_visit == T0 + 600


def test_visit_in_progress_from_0_2_2_storage_loads():
    t = Tracker(3.0)
    t.apply(rec(id=1, time=T0, waste="urine", final=1), T0)
    data = t.to_dict()
    cat = data["cats"]["4"]
    del cat["sits"]
    cat.update(sit_start=T0, sit_last=T0, sit_waste="urine")
    t2 = Tracker.from_dict(data, 3.0)
    t2.apply(rec(id=2, time=T0 + 60, waste="urine", final=1), T0 + 60)
    assert (t2.cats[4].visits, t2.cats[4].pee) == (1, 1)
    del cat["sit_start"], cat["sit_last"], cat["sit_waste"]
    assert Tracker.from_dict(data, 3.0).cats[4].sits == []
