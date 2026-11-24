"""Shared fixtures."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clowder.const import DOMAIN

T0 = 1_000_000
ACK = "litter_robot4_lr4c000001_clowder_ack"
HELLO = {
    "node": "litter-robot4-lr4c000001",
    "robot": "LR4C000001",
    "cats": "1=Ash,2=Bean,3=Coco,4=Luna,5=Milo,6=Nori",
}


def ev(**kw):
    base = {
        "node": "litter-robot4-lr4c000001",
        "robot": "LR4C000001",
        "epoch": "7",
        "id": "1",
        "slot": "4",
        "name": "Luna",
        "method": "Tag",
        "rssi": "-52",
        "weight": "11.46",
        "time": "0",
        "age": "5",
        "waste": "pending",
        "waste_weight": "",
        "final": "0",
    }
    return base | {k: str(v) for k, v in kw.items()}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""


@pytest.fixture
async def entry(hass):
    """A loaded Clowder config entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Clowder", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def hub(entry):
    return entry.runtime_data
