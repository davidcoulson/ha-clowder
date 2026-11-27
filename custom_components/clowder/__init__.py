"""Clowder: one device per cat, fed by litter robot visit events."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.loader import BASE_PRELOAD_PLATFORMS, async_get_integration

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
    hass.data[DOMAIN]["card_url"] = f"{CARD_URL}?v={version}"
    add_extra_js_url(hass, hass.data[DOMAIN]["card_url"])


def _manifest_version() -> str:
    return json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


async def _async_refresh_card_url(hass: HomeAssistant) -> None:
    """Point dashboards at the card on disk: its ?v= was built when the card was first loaded."""
    data = hass.data.get(DOMAIN, {})
    new = f"{CARD_URL}?v={await hass.async_add_executor_job(_manifest_version)}"
    if (old := data.get("card_url")) and old != new:
        remove_extra_js_url(hass, old)
        add_extra_js_url(hass, new)
        data["card_url"] = new


def _import_code(package: str) -> None:
    """Import the new code in the import executor, not the event loop.

    After an unload HA still lists "<domain>.<platform>" as loaded, so it
    would import the new modules in the event loop (and warn about it);
    once they are in sys.modules its own import is a cache hit.
    """
    module = importlib.import_module(package)
    # The new module's list, plus what HA preloads with a package (diagnostics, ...).
    for name in (*module.PLATFORMS, *BASE_PRELOAD_PLATFORMS):
        if importlib.util.find_spec(f"{package}.{name}") is not None:
            importlib.import_module(f"{package}.{name}")


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
                raise HomeAssistantError(f"{DOMAIN} did not unload; restart Home Assistant instead")
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


_CODE_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


def _code_signature() -> str | None:
    """sha256 of the .py files and the manifest's requirements (blocking: run in the executor)."""
    root = Path(__file__).parent
    try:
        digest = hashlib.sha256()
        for path in sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
        manifest = json.loads((root / "manifest.json").read_text())
        digest.update(json.dumps(manifest.get("requirements", [])).encode())
    except OSError:
        return None
    return digest.hexdigest()


# The Python this import is, hashed once: an options reload runs setup again on the same modules,
# and reload_code imports a fresh module, which starts at None.
_RUNNING_CODE: str | None = None


def _clear_marketplace_restart(hass: HomeAssistant, same_code: bool = False) -> None:
    """Drop Marketplace's "restart to finish the update" repair for the running Clowder version.

    Called from entry setup, so it uses the new code's version even when the old handler did
    the reload; a repair for any other version still waits, unless ``same_code``: the Python
    on disk is the code running, so the update changed only the frontend.
    """
    for (domain, issue_id), issue in list(ir.async_get(hass).issues.items()):
        if (
            domain == "marketplace"
            and issue_id.startswith("restart_required_")
            and issue.issue_domain == DOMAIN
            and (same_code or issue_id.rsplit("/", 1)[-1].removeprefix("v") == _CODE_VERSION)
        ):
            ir.async_delete_issue(hass, domain, issue_id)


async def _clear_restart_if_same_code(hass: HomeAssistant) -> None:
    """Drop our restart repairs when the Python on disk is the code running (frontend-only)."""
    if (
        _RUNNING_CODE is not None
        and await hass.async_add_executor_job(_code_signature) == _RUNNING_CODE
    ):
        _clear_marketplace_restart(hass, same_code=True)
        await _async_refresh_card_url(hass)


def _listen_for_restart_repairs(hass: HomeAssistant) -> None:
    """One listener for the domain, however many entries (the repair comes after the files)."""
    data = hass.data.setdefault(DOMAIN, {})
    if "repair_unsub" in data:
        return

    async def _on_issue(event) -> None:
        if (
            event.data.get("action") in ("create", "update")
            and event.data.get("domain") == "marketplace"
            and str(event.data.get("issue_id", "")).startswith("restart_required_")
        ):
            await _clear_restart_if_same_code(hass)

    data["repair_unsub"] = hass.bus.async_listen("repairs_issue_registry_updated", _on_issue)


async def async_setup_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    global _RUNNING_CODE  # noqa: PLW0603
    _register_reload_code(hass)
    await _async_register_cards(hass)
    if _RUNNING_CODE is None:
        _RUNNING_CODE = await hass.async_add_executor_job(_code_signature)
    hub = ClowderHub(hass, entry)
    await hub.async_start()
    entry.runtime_data = hub
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _listen_for_restart_repairs(hass)  # before the sweep: a repair raised in between is caught
    _clear_marketplace_restart(hass)
    await _clear_restart_if_same_code(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClowderConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(  # pragma: no branch
        entry, PLATFORMS
    ):
        await entry.runtime_data.async_stop()
        # The last entry going also covers reload_code: the fresh module registers its own listener.
        if not any(
            e is not entry and e.state is ConfigEntryState.LOADED
            for e in hass.config_entries.async_entries(DOMAIN)
        ) and (unsub := hass.data.get(DOMAIN, {}).pop("repair_unsub", None)):
            unsub()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ClowderConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
