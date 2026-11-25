"""Per-cat sensors, and the rollup sensors on the Clowder device."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .entity import HUB_DEVICE, ClowderCatEntity, setup_cat_platform
from .hub import SIGNAL_ROLLUP, ClowderHub
from .model import CatState, Tracker

REFRESH = timedelta(minutes=5)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True, kw_only=True)
class ClowderSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CatState, float], float | int | str | None]
    time_based: bool = False  # changes as time passes, not only on a visit


_WEIGHT = {
    "device_class": SensorDeviceClass.WEIGHT,
    "native_unit_of_measurement": UnitOfMass.POUNDS,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 2,
}
_COUNT = {"state_class": SensorStateClass.TOTAL_INCREASING}

SENSORS: tuple[ClowderSensorDescription, ...] = (
    ClowderSensorDescription(key="weight", value_fn=lambda c, now: c.weight, **_WEIGHT),
    ClowderSensorDescription(
        key="average_weight_7d",
        value_fn=lambda c, now: _round(c.avg_weight_7d(now), 2),
        time_based=True,
        **_WEIGHT,
    ),
    ClowderSensorDescription(key="visits", value_fn=lambda c, now: c.visits, **_COUNT),
    ClowderSensorDescription(
        key="visits_per_day_7d",
        value_fn=lambda c, now: round(c.visits_per_day_7d(now), 1),
        state_class=SensorStateClass.MEASUREMENT,
        time_based=True,
    ),
    ClowderSensorDescription(
        key="hours_since_last_visit",
        value_fn=lambda c, now: _round(c.hours_since_last_visit(now), 1),
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        time_based=True,
    ),
    ClowderSensorDescription(key="poop_count", value_fn=lambda c, now: c.poop, **_COUNT),
    ClowderSensorDescription(key="pee_count", value_fn=lambda c, now: c.pee, **_COUNT),
    ClowderSensorDescription(key="poop_weight", value_fn=lambda c, now: c.poop_weight, **_WEIGHT),
    ClowderSensorDescription(key="pee_weight", value_fn=lambda c, now: c.pee_weight, **_WEIGHT),
    ClowderSensorDescription(key="last_robot", value_fn=lambda c, now: c.last_robot),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_cat_platform(
        hass,
        entry,
        async_add_entities,
        lambda hub, slot: [ClowderSensor(hub, slot, description) for description in SENSORS],
    )
    async_add_entities(ClowderHubSensor(entry.runtime_data, key) for key in HUB_SENSORS)


class ClowderSensor(ClowderCatEntity, SensorEntity):
    entity_description: ClowderSensorDescription

    def __init__(self, hub: ClowderHub, slot: int, description: ClowderSensorDescription) -> None:
        super().__init__(hub, slot, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.cat, dt_util.utcnow().timestamp())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "visits_per_day_7d":
            return None
        # The share card reads this to draw who uses which robot.
        return {"robots": self.cat.robots_7d(dt_util.utcnow().timestamp())}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.time_based:
            self.async_on_remove(async_track_time_interval(self.hass, self._tick, REFRESH))

    @callback
    def _tick(self, now: datetime) -> None:
        self.async_write_ha_state()


def _last_visit(t: Tracker) -> datetime | None:
    return datetime.fromtimestamp(t.last[0], UTC) if t.last else None


# key -> (value, device class, state class)
HUB_SENSORS: dict[str, tuple[Callable[[Tracker], Any], SensorDeviceClass | None, str | None]] = {
    "last_cat": (lambda t: t.last[1] if t.last else None, None, None),
    "last_visit": (_last_visit, SensorDeviceClass.TIMESTAMP, None),
    "visits_today": (
        lambda t: t.visits_since(dt_util.start_of_local_day().timestamp()),
        None,
        SensorStateClass.MEASUREMENT,
    ),
    "unidentified_visits": (lambda t: t.unidentified, None, SensorStateClass.TOTAL_INCREASING),
}


class ClowderHubSensor(SensorEntity):
    """A rollup across all cats, on the Clowder device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_info = HUB_DEVICE

    def __init__(self, hub: ClowderHub, key: str) -> None:
        self.hub = hub
        self._value, self._attr_device_class, self._attr_state_class = HUB_SENSORS[key]
        self._attr_translation_key = key
        self._attr_unique_id = f"clowder_hub_{key}"

    @property
    def native_value(self) -> Any:
        return self._value(self.hub.tracker)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        last = self.hub.tracker.last
        if self._attr_translation_key != "last_visit" or last is None:
            return None
        return {"robot": last[2]}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_ROLLUP, self._refresh))
        if self._attr_translation_key == "visits_today":  # falls back to 0 after midnight
            self.async_on_remove(async_track_time_interval(self.hass, self._refresh, REFRESH))

    @callback
    def _refresh(self, now: datetime | None = None) -> None:
        self.async_write_ha_state()
