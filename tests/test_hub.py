"""Event handling, storage and acknowledgement."""

from unittest.mock import AsyncMock

from homeassistant.core import CoreState
from homeassistant.helpers import issue_registry as ir

from custom_components.clowder.const import DOMAIN, EVENT_HELLO, EVENT_VISIT

from .conftest import ACK, HELLO, MockConfigEntry, async_mock_service, ev


async def fire(hass, event, data):
    hass.bus.async_fire(event, data)
    await hass.async_block_till_done()


async def test_visit_event_counts_and_acks(hass, hub):
    calls = async_mock_service(hass, "esphome", ACK)
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert hub.tracker.cats[4].visits == 1
    assert hub.tracker.cats[4].pee == 1
    assert len(calls) == 1
    assert calls[0].data == {"epoch": 7, "id": 1}


async def test_repeat_final_is_acked_again(hass, hub):
    calls = async_mock_service(hass, "esphome", ACK)
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert hub.tracker.cats[4].visits == 1
    assert len(calls) == 2


async def test_no_ack_service_still_counts(hass, hub):
    await fire(hass, EVENT_VISIT, ev(waste="feces", final=1))
    assert hub.tracker.cats[4].visits == 1
    assert hub.tracker.cats[4].poop == 1


async def test_pending_is_not_acked(hass, hub):
    calls = async_mock_service(hass, "esphome", ACK)
    await fire(hass, EVENT_VISIT, ev())
    assert hub.tracker.cats[4].visits == 1
    assert calls == []


async def test_junk_events_do_not_raise(hass, hub, caplog):
    await fire(hass, EVENT_VISIT, ev(slot=9))
    await fire(hass, EVENT_VISIT, {})
    await fire(hass, EVENT_HELLO, {"cats": "junk,=,9=Nine,x=y,2=Bean"})
    await fire(hass, EVENT_HELLO, {})
    assert list(hub.tracker.cats) == [2]
    assert "Traceback" not in caplog.text


async def test_state_survives_reload(hass, entry):
    await fire(hass, EVENT_VISIT, ev())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await fire(hass, EVENT_VISIT, ev(id=2))  # not listening while unloaded
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.tracker.cats[4].visits == 1
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert entry.runtime_data.tracker.cats[4].visits == 1
    assert entry.runtime_data.tracker.cats[4].pee == 1


async def test_hello_creates_cats_and_flags_conflict(hass, hub):
    await fire(hass, EVENT_HELLO, HELLO)
    assert sorted(hub.tracker.cats) == [1, 2, 3, 4, 5, 6]
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "name_conflict_4") is None
    await fire(hass, EVENT_HELLO, HELLO | {"robot": "OTHER", "cats": "4=Nori"})
    assert registry.async_get_issue(DOMAIN, "name_conflict_4") is not None
    assert hub.tracker.cats[4].name == "Luna"


async def test_reset_and_set_weight(hass, hub):
    await fire(hass, EVENT_VISIT, ev())
    await hub.async_set_weight(4, 12.0)
    assert hub.tracker.cats[4].weight == 12.0
    await hub.async_reset(4)
    assert hub.tracker.cats[4].visits == 0


async def test_final_is_saved_before_ack(hass, hub, hass_storage):
    """The robot forgets a record once acknowledged, so it must be on disk first."""
    saved_at_ack = []

    async def on_ack(call):
        saved_at_ack.append(hass_storage[DOMAIN]["data"]["cats"]["4"]["visits"])

    hass.services.async_register("esphome", ACK, on_ack)
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert saved_at_ack == [1]


async def test_failed_ack_is_not_an_error(hass, hub, caplog):
    async def on_ack(call):
        raise RuntimeError("robot went away")

    hass.services.async_register("esphome", ACK, on_ack)
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert hub.tracker.cats[4].pee == 1
    assert "Traceback" not in caplog.text
    assert "ERROR" not in caplog.text


async def test_hello_with_odd_digits_does_not_raise(hass, hub, caplog):
    await fire(hass, EVENT_HELLO, {"cats": "²=Two,٣=Three,1=Ash"})
    assert list(hub.tracker.cats) == [1]
    assert "Traceback" not in caplog.text


async def test_no_ack_when_the_save_did_not_reach_disk(hass, hub, hass_storage):
    """Home Assistant logs a failed write instead of raising, so check what is on disk."""
    calls = async_mock_service(hass, "esphome", ACK)
    hub._store.async_save = AsyncMock()
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert hub.tracker.cats[4].pee == 1
    assert calls == []


async def test_no_ack_while_stopping(hass, hub, hass_storage):
    """Saves are put off until the final write when stopping; the robot resends after."""
    calls = async_mock_service(hass, "esphome", ACK)
    hass.set_state(CoreState.stopping)
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))
    assert calls == []


async def test_damaged_storage_starts_empty_and_keeps_a_copy(hass, hass_storage, caplog):
    damaged = {"cats": {"4": {"nmae": "Luna"}}, "seen": {"R": [[1]]}}
    hass_storage[DOMAIN] = {"version": 1, "minor_version": 1, "key": DOMAIN, "data": damaged}
    entry = MockConfigEntry(domain=DOMAIN, title="Clowder", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.tracker.cats == {}
    assert hass_storage[f"{DOMAIN}.damaged"]["data"] == damaged
    assert "damaged" in caplog.text


async def test_real_clock_times_reach_the_tracker(hass, hub, freezer):
    freezer.move_to("2026-11-24 12:00:00+00:00")
    now = 1795521600
    await fire(hass, EVENT_VISIT, ev(time=now - 60))
    assert hub.tracker.cats[4].last_visit == now - 60
