"""Set Weight: correct a cat's weight by hand."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ClowderCatEntity, setup_cat_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_cat_platform(
        hass, entry, async_add_entities, lambda hub, slot: [ClowderSetWeight(hub, slot)]
    )


class ClowderSetWeight(ClowderCatEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.POUNDS
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub, slot: int) -> None:
        super().__init__(hub, slot, "set_weight")

    @property
    def native_value(self) -> float | None:
        return self.cat.weight

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.async_set_weight(self.slot, value)
