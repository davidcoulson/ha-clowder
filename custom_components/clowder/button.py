"""Tracker Reset: zero a cat's counts and history."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ClowderCatEntity, setup_cat_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_cat_platform(
        hass, entry, async_add_entities, lambda hub, slot: [ClowderTrackerReset(hub, slot)]
    )


class ClowderTrackerReset(ClowderCatEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, slot: int) -> None:
        super().__init__(hub, slot, "tracker_reset")

    async def async_press(self) -> None:
        await self.hub.async_reset(self.slot)
