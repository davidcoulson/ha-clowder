"""Clowder: one device per cat, fed by litter robot visit events."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
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


def _import_code(package: str) -> None:
    """Import the new package and its platforms in the executor, so HA's own import is a cache hit."""
    for platform in importlib.import_module(package).PLATFORMS:
        importlib.import_module(f"{package}.{platform}")


def _forget_code(hass: HomeAssistant, package: str, domain: str) -> None:
    """Drop a package's modules so the next setup imports them from disk again.

    Home Assistant keeps its own copy of each imported integration module
    (loader.py: hass.data["components"], keyed "<domain>" and
    "<domain>.<platform>") next to Python's sys.modules; both have to go.
    """
    for cache, root in (
        (sys.modules, package),
        (hass.data.get("components", {}), domain),
        (hass.data.get("missing_platforms", {}), domain),
    ):
        for name in [n for n in cache if n == root or n.startswith(root + ".")]:
            del cache[name]
    importlib.invalidate_caches()  # or a file added since the last import may not be found


def _register_reload_code(hass: HomeAssistant) -> None:
    """Dev: clowder.reload_code loads the Python files from disk without a restart."""

    async def _reload_code(call: ServiceCall) -> None:
        # Disabled and ignored entries are never set up, so they are not ours to reload.
        entries = hass.config_entries.async_entries(
            DOMAIN, include_ignore=False, include_disabled=False
        )
        for entry in entries:
            if not await hass.config_entries.async_unload(entry.entry_id):
                raise HomeAssistantError(
                    f"{DOMAIN} did not unload; restart Home Assistant instead"
                )
        _forget_code(hass, __name__, DOMAIN)
        try:
            await hass.async_add_import_executor_job(_import_code, __name__)
        except Exception as err:
            # This handler stays registered, so the action works again once the code is fixed.
            raise HomeAssistantError(
                f"{DOMAIN} is unloaded: the new code did not load ({err}). "
                f"Fix it and call {DOMAIN}.reload_code again"
            ) from err
        failed = [e.title for e in entries if not await hass.config_entries.async_setup(e.entry_id)]
        if failed:
            raise HomeAssistantError(f"{DOMAIN} did not set up again for {failed}; see the log")

    async_register_admin_service(hass, DOMAIN, "reload_code", _reload_code)


async def async_setup_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    _register_reload_code(hass)
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
