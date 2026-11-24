"""Clowder: one device per cat, fed by litter robot visit events."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .hub import ClowderHub

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.EVENT, Platform.NUMBER, Platform.SENSOR]

type ClowderConfigEntry = ConfigEntry[ClowderHub]


async def async_setup_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    hub = ClowderHub(hass, entry)
    await hub.async_start()
    entry.runtime_data = hub
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(  # pragma: no branch
        entry, PLATFORMS
    ):
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ClowderConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
