"""Base entity and per-cat platform setup."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import SIGNAL_NEW_CAT, SIGNAL_UPDATE, ClowderHub
from .model import CatState


class ClowderCatEntity(Entity):
    """An entity on a cat's device; rewrites its state when that cat changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: ClowderHub, slot: int, key: str) -> None:
        self.hub = hub
        self.slot = slot
        self._attr_translation_key = key
        self._attr_unique_id = f"clowder_{slot}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"cat_{slot}")},
            name=hub.tracker.cats[slot].name,
            manufacturer="Clowder",
            model="Cat",
        )

    @property
    def cat(self) -> CatState:
        return self.hub.tracker.cats[self.slot]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._on_update))

    @callback
    def _on_update(self, slot: int) -> None:
        if slot == self.slot:
            self.async_write_ha_state()


def setup_cat_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    make: Callable[[ClowderHub, int], Iterable[Entity]],
) -> None:
    """Add entities for every known cat, and for each cat that appears later."""
    hub: ClowderHub = entry.runtime_data

    @callback
    def add(slot: int) -> None:
        async_add_entities(make(hub, slot))

    for slot in hub.tracker.cats:
        add(slot)
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_CAT, add))
