"""The dev-only reload_code action swaps in the Python files on disk."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from custom_components import clowder
from custom_components.clowder.const import DOMAIN


async def test_reload_code_replaces_the_modules(hass, entry) -> None:
    old = {n: m for n, m in sys.modules.items() if n.startswith("custom_components.clowder")}
    assert hass.services.has_service(DOMAIN, "reload_code")

    await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is not old["custom_components.clowder"]
    const = "custom_components.clowder.const"
    assert sys.modules[const] is not old[const]
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


async def test_reload_clears_only_marketplaces_running_version_repairs(hass, monkeypatch):
    mod = clowder
    monkeypatch.setattr(mod, "_CODE_VERSION", "1.2.3")
    for domain, issue_id, issue_domain in (
        ("marketplace", "restart_required_1_tags/1.2.3", "clowder"),
        ("marketplace", "restart_required_2_tags/v1.2.3", "clowder"),
        ("marketplace", "restart_required_3_tags/1.2.4", "clowder"),
        ("marketplace", "restart_required_4_tags/1.2.3", "ssh"),
        ("marketplace", "critical_x/1.2.3", "clowder"),
        ("clowder", "restart_required_x/1.2.3", "clowder"),
    ):
        ir.async_create_issue(
            hass,
            domain,
            issue_id,
            is_fixable=False,
            issue_domain=issue_domain,
            severity=ir.IssueSeverity.WARNING,
            translation_key="x",
        )
    mod._clear_marketplace_restart(hass)
    assert set(ir.async_get(hass).issues) == {
        ("marketplace", "restart_required_3_tags/1.2.4"),
        ("marketplace", "restart_required_4_tags/1.2.3"),
        ("marketplace", "critical_x/1.2.3"),
        ("clowder", "restart_required_x/1.2.3"),
    }


def test_code_version_is_the_manifest_version():
    mod = clowder
    manifest = json.loads((Path(mod.__file__).parent / "manifest.json").read_text())
    assert manifest["version"] == mod._CODE_VERSION


def _restart_repairs(hass):
    for domain, issue_id, issue_domain in (
        ("marketplace", "restart_required_1_tags/1.2.3", "clowder"),
        ("marketplace", "restart_required_1_tags/1.2.4", "clowder"),
        ("marketplace", "restart_required_4_tags/1.2.3", "ssh"),
        ("marketplace", "critical_x/1.2.3", "clowder"),
    ):
        ir.async_create_issue(
            hass,
            domain,
            issue_id,
            is_fixable=False,
            issue_domain=issue_domain,
            severity=ir.IssueSeverity.WARNING,
            translation_key="x",
        )


async def test_same_python_clears_every_restart_repair_for_us(hass, monkeypatch):
    _restart_repairs(hass)
    monkeypatch.setattr(clowder, "_RUNNING_CODE", "old")
    monkeypatch.setattr(clowder, "_code_signature", lambda: "new")
    await clowder._clear_restart_if_same_code(hass)
    assert len(ir.async_get(hass).issues) == 4  # changed Python: they stay
    monkeypatch.setattr(clowder, "_code_signature", lambda: "old")
    await clowder._clear_restart_if_same_code(hass)
    assert set(ir.async_get(hass).issues) == {
        ("marketplace", "restart_required_4_tags/1.2.3"),
        ("marketplace", "critical_x/1.2.3"),
    }


async def test_a_new_repair_is_cleared_by_the_listener(hass, entry, monkeypatch):
    monkeypatch.setattr(clowder, "_code_signature", lambda: clowder._RUNNING_CODE)
    _restart_repairs(hass)
    await hass.async_block_till_done()
    assert set(ir.async_get(hass).issues) == {
        ("marketplace", "restart_required_4_tags/1.2.3"),
        ("marketplace", "critical_x/1.2.3"),
    }


def test_signature_follows_python_and_requirements(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "sub" / "b.py").write_text("y = 2")
    (tmp_path / "manifest.json").write_text('{"requirements": []}')
    with patch.object(clowder, "__file__", str(tmp_path / "__init__.py")):
        base = clowder._code_signature()
        (tmp_path / "manifest.json").write_text('{"requirements": ["foo==1"]}')
        assert clowder._code_signature() != base
        (tmp_path / "manifest.json").write_text('{"requirements": []}')
        assert clowder._code_signature() == base
        (tmp_path / "sub" / "b.py").write_text("y = 3")
        assert clowder._code_signature() != base


async def test_two_entries_register_one_listener(hass, entry):
    first = hass.data[DOMAIN]["repair_unsub"]
    clowder._listen_for_restart_repairs(hass)  # what a second entry's setup does
    assert hass.data[DOMAIN]["repair_unsub"] is first
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "repair_unsub" not in hass.data[DOMAIN]


def test_signature_is_none_when_the_package_is_unreadable(tmp_path):
    with patch.object(clowder, "__file__", str(tmp_path / "__init__.py")):  # no manifest.json
        assert clowder._code_signature() is None


async def test_the_listener_stays_while_another_entry_is_loaded(hass, entry):
    other = type("E", (), {"state": ConfigEntryState.LOADED})()
    with patch.object(ConfigEntries, "async_entries", return_value=[entry, other]):
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert "repair_unsub" in hass.data[DOMAIN]


async def test_same_code_clear_moves_the_card_url_to_the_new_version(hass, entry, monkeypatch):
    from custom_components.clowder import CARD_URL

    monkeypatch.setattr(clowder, "_RUNNING_CODE", "same")
    monkeypatch.setattr(clowder, "_code_signature", lambda: "same")
    monkeypatch.setattr(clowder, "_manifest_version", lambda: "9.9.9")
    with (
        patch.object(clowder, "remove_extra_js_url") as remove,
        patch.object(clowder, "add_extra_js_url") as add,
    ):
        old = hass.data[DOMAIN]["card_url"]
        await clowder._clear_restart_if_same_code(hass)
        remove.assert_called_once_with(hass, old)
        add.assert_called_once_with(hass, f"{CARD_URL}?v=9.9.9")
        # Unchanged URL: nothing more.
        await clowder._clear_restart_if_same_code(hass)
        remove.assert_called_once()


def test_manifest_version_is_read_from_disk():
    assert clowder._manifest_version() == clowder._CODE_VERSION


async def test_a_syntax_error_unloads_nothing(hass, entry, tmp_path):
    old = sys.modules["custom_components.clowder"]
    (tmp_path / "const.py").write_text("X = (\n")
    with (
        # the running module: earlier reload tests left the imported name stale
        patch.object(old, "__file__", str(tmp_path / "__init__.py")),
        pytest.raises(HomeAssistantError, match=r"const\.py line 1.*unchanged"),
    ):
        await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is old


async def test_an_import_error_puts_the_previous_code_back(hass, entry):
    old = sys.modules["custom_components.clowder"]
    real = importlib.import_module

    def broken(name, *a, **k):
        if name == "custom_components.clowder" and name not in sys.modules:
            raise ImportError("no_such_name")
        return real(name, *a, **k)

    with (
        patch.object(importlib, "import_module", broken),
        pytest.raises(HomeAssistantError, match="previous code is running again"),
    ):
        await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is old
    assert hass.bus.async_listeners()["repairs_issue_registry_updated"] == 1
    # the action works again once the code is fixed
    await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is not old


def _broken_import(old):
    """An import_module whose fresh copy of the package has a hub that fails to start."""
    real = importlib.import_module

    def broken(name, *a, **k):
        module = real(name, *a, **k)
        if name == "custom_components.clowder" and module is not old:
            sys.modules["custom_components.clowder.hub"].ClowderHub.async_start = _boom
        return module

    return broken


async def _boom(self):
    raise RuntimeError("broken")


async def test_a_setup_error_puts_the_previous_code_back(hass, entry):
    old = sys.modules["custom_components.clowder"]
    old_hub = sys.modules["custom_components.clowder.hub"]
    old.async_setup = setup = AsyncMock(return_value=True)  # the old async_setup runs again
    try:
        with (
            patch.object(importlib, "import_module", _broken_import(old)),
            pytest.raises(HomeAssistantError, match="did not set up.*previous code"),
        ):
            await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    finally:
        del old.async_setup
    setup.assert_awaited_once_with(hass, {})
    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.clowder"] is old
    assert sys.modules["custom_components.clowder.hub"] is old_hub
    assert hass.bus.async_listeners()["repairs_issue_registry_updated"] == 1


async def test_a_failed_rollback_says_to_restart(hass, entry):
    old = sys.modules["custom_components.clowder"]
    old_hub = sys.modules["custom_components.clowder.hub"]
    with (
        patch.object(old_hub.ClowderHub, "async_start", _boom),  # the old code breaks too
        patch.object(importlib, "import_module", _broken_import(old)),
        pytest.raises(HomeAssistantError, match="restart Home Assistant"),
    ):
        await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
