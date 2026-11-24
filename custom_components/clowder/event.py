"""Unidentified Visit: fires when a robot could not match a visit to a cat."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import SIGNAL_UNIDENTIFIED
from .model import VisitRecord

EVENT_TYPE = "unidentified_visit"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ClowderUnidentifiedVisit()])


class ClowderUnidentifiedVisit(EventEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = EVENT_TYPE
    _attr_unique_id = "clowder_unidentified_visit"
    _attr_event_types = [EVENT_TYPE]
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "hub")},
        name="Clowder",
        manufacturer="Clowder",
        entry_type=DeviceEntryType.SERVICE,
    )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UNIDENTIFIED, self._on_visit)
        )

    @callback
    def _on_visit(self, rec: VisitRecord) -> None:
        self._trigger_event(
            EVENT_TYPE,
            {
                "robot": rec.robot,
                "weight": rec.weight,
                "time": datetime.fromtimestamp(rec.when, UTC).isoformat(),
                "rssi": rec.rssi,
            },
        )
        self.async_write_ha_state()
