"""The dev-only reload_code action swaps in the Python files on disk."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.clowder.const import DOMAIN


async def test_reload_code_replaces_the_modules(hass, entry) -> None:
    old = {n: m for n, m in sys.modules.items() if n.startswith("custom_components.clowder")}
    assert hass.services.has_service(DOMAIN, "reload_code")

    await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is not old["custom_components.clowder"]
    assert sys.modules["custom_components.clowder.const"] is not old["custom_components.clowder.const"]
    assert hass.services.has_service(DOMAIN, "reload_code")


@pytest.mark.parametrize(
    ("target", "result"),
    [
        (ConfigEntries, "async_unload"),
        (importlib, "import_module"),
        (ConfigEntries, "async_setup"),
    ],
)
async def test_reload_code_reports_failures(hass, entry, target, result) -> None:
    kwargs = {"return_value": False}
    if target is importlib:  # unload needs the old module; only the fresh import fails
        real = importlib.import_module

        def kwargs_wrapper(name, *a, **k):
            if name == "custom_components.clowder" and name not in sys.modules:
                raise ImportError("boom")
            return real(name, *a, **k)

        kwargs = {"new": kwargs_wrapper}
    with patch.object(target, result, **kwargs), pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    # the action survives a failed reload, so it can be called again once the code is fixed
    assert hass.services.has_service(DOMAIN, "reload_code")
