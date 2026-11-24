"""Cat devices and their entities."""

from datetime import timedelta

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.clowder.const import DOMAIN, EVENT_HELLO, EVENT_VISIT

from .conftest import HELLO, ev


async def fire(hass, event, data):
    hass.bus.async_fire(event, data)
    await hass.async_block_till_done()


def state(hass, entity_id):
    found = hass.states.get(entity_id)
    assert found is not None, entity_id
    return found.state


async def test_hello_creates_six_devices_with_twelve_entities(hass, entry):
    await fire(hass, EVENT_HELLO, HELLO)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    for slot, name in enumerate(["Ash", "Bean", "Coco", "Luna", "Milo", "Nori"], 1):
        device = devices.async_get_device({(DOMAIN, f"cat_{slot}")})
        assert device is not None and device.name == name
        assert len(er.async_entries_for_device(entities, device.id)) == 12
    hub_device = devices.async_get_device({(DOMAIN, "hub")})
    assert len(er.async_entries_for_device(entities, hub_device.id)) == 5
    assert state(hass, "sensor.ash_visits") == "0"
    assert state(hass, "sensor.ash_weight") == "unknown"
    assert state(hass, "sensor.ash_hours_since_last_visit") == "unknown"
    await fire(hass, EVENT_HELLO, HELLO)  # a second hello adds nothing
    assert len(er.async_entries_for_config_entry(entities, entry.entry_id)) == 77


async def test_visit_updates_sensors(hass, entry):
    await fire(hass, EVENT_HELLO, HELLO)
    await fire(hass, EVENT_VISIT, ev())
    assert state(hass, "sensor.luna_visits") == "1"
    assert state(hass, "sensor.luna_pee_count") == "0"
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1, waste_weight="0.05"))
    assert state(hass, "sensor.luna_visits") == "1"
    assert state(hass, "sensor.luna_pee_count") == "1"
    assert state(hass, "sensor.luna_poop_count") == "0"
    assert state(hass, "sensor.luna_weight") == "11.46"
    assert state(hass, "sensor.luna_average_weight_7d") == "11.46"
    assert state(hass, "sensor.luna_visits_per_day_7d") == "0.1"
    assert state(hass, "sensor.luna_pee_weight") == "0.05"
    assert state(hass, "sensor.luna_poop_weight") == "unknown"
    assert state(hass, "sensor.luna_last_robot") == "LR4C000001"
    assert state(hass, "number.luna_set_weight") == "11.46"
    assert state(hass, "sensor.ash_visits") == "0"


async def test_hours_since_last_visit_advances(hass, entry, freezer):
    await fire(hass, EVENT_VISIT, ev(age=0))
    assert state(hass, "sensor.luna_hours_since_last_visit") == "0.0"
    freezer.tick(timedelta(hours=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert state(hass, "sensor.luna_hours_since_last_visit") == "3.0"


async def test_reset_button_zeroes(hass, entry):
    await fire(hass, EVENT_VISIT, ev(waste="feces", final=1))
    assert state(hass, "sensor.luna_poop_count") == "1"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.luna_tracker_reset"}, blocking=True
    )
    await hass.async_block_till_done()
    assert state(hass, "sensor.luna_visits") == "0"
    assert state(hass, "sensor.luna_poop_count") == "0"
    assert state(hass, "sensor.luna_weight") == "unknown"


async def test_set_weight_number(hass, entry):
    await fire(hass, EVENT_HELLO, HELLO)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.nori_set_weight", "value": 9.5}, blocking=True
    )
    await hass.async_block_till_done()
    assert state(hass, "sensor.nori_weight") == "9.5"
    assert state(hass, "number.nori_set_weight") == "9.5"


async def test_unidentified_fires_event_entity_once(hass, entry, freezer):
    assert state(hass, "event.clowder_unidentified_visit") == "unknown"
    await fire(hass, EVENT_VISIT, ev(slot=0, name="Unknown", method="None", rssi=-90))
    first = hass.states.get("event.clowder_unidentified_visit")
    assert first.state != "unknown"
    assert first.attributes["robot"] == "LR4C000001"
    assert first.attributes["weight"] == 11.46
    assert first.attributes["rssi"] == -90
    assert first.attributes["time"].startswith("20")
    freezer.tick(60)
    await fire(hass, EVENT_VISIT, ev(slot=0, name="Unknown", final=1, waste="urine"))
    assert hass.states.get("event.clowder_unidentified_visit").state == first.state
    assert dr.async_get(hass).async_get_device({(DOMAIN, "cat_0")}) is None


async def test_cat_first_seen_by_visit_gets_device(hass, entry):
    await fire(hass, EVENT_VISIT, ev(slot=2, name="Bean"))
    assert state(hass, "sensor.bean_visits") == "1"
    assert dr.async_get(hass).async_get_device({(DOMAIN, "cat_2")}).name == "Bean"


async def test_entities_restored_after_reload(hass, entry):
    await fire(hass, EVENT_VISIT, ev())
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor.luna_visits") == "1"


async def test_rollup_sensors(hass, entry):
    await fire(hass, EVENT_HELLO, HELLO)
    assert state(hass, "sensor.clowder_last_cat") == "unknown"
    assert state(hass, "sensor.clowder_last_visit") == "unknown"
    assert state(hass, "sensor.clowder_visits_today") == "0"
    assert state(hass, "sensor.clowder_unidentified_visits") == "0"
    await fire(hass, EVENT_VISIT, ev())
    await fire(hass, EVENT_VISIT, ev(waste="urine", final=1))  # same visit again
    assert state(hass, "sensor.clowder_last_cat") == "Luna"
    assert state(hass, "sensor.clowder_visits_today") == "1"
    last = hass.states.get("sensor.clowder_last_visit")
    assert last.state not in ("unknown", "unavailable")
    assert last.attributes["robot"] == "LR4C000001"
    await fire(hass, EVENT_VISIT, ev(id=2, slot=0, name="Unknown", method="None", age=0))
    assert state(hass, "sensor.clowder_last_cat") == "Unknown"
    assert state(hass, "sensor.clowder_visits_today") == "2"
    assert state(hass, "sensor.clowder_unidentified_visits") == "1"


async def test_late_record_from_another_day_is_not_today_or_last(hass, entry):
    await fire(hass, EVENT_HELLO, HELLO)
    await fire(hass, EVENT_VISIT, ev())
    await fire(hass, EVENT_VISIT, ev(id=2, slot=1, name="Ash", age=30 * 3600))
    assert state(hass, "sensor.ash_visits") == "1"
    assert state(hass, "sensor.clowder_visits_today") == "1"
    assert state(hass, "sensor.clowder_last_cat") == "Luna"
