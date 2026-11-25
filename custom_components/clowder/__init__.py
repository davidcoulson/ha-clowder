"""Clowder: one device per cat, fed by litter robot visit events."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .hub import ClowderHub

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.EVENT, Platform.NUMBER, Platform.SENSOR]

CARD_URL = "/clowder/clowder-card.js"

type ClowderConfigEntry = ConfigEntry[ClowderHub]


async def _async_register_cards(hass: HomeAssistant) -> None:
    """Serve the dashboard cards and have every dashboard load them. Once per run."""
    if hass.data.setdefault(DOMAIN, {}).get("cards"):
        return
    hass.data[DOMAIN]["cards"] = True
    path = Path(__file__).parent / "clowder-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    # The version in the address makes browsers fetch the new file after an update.
    version = (await async_get_integration(hass, DOMAIN)).version
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    await _async_register_cards(hass)
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
