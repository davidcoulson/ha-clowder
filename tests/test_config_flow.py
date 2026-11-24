"""Config and options flow."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.clowder.const import CONF_MAX_WEIGHT_JUMP, DOMAIN


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Clowder"
    await hass.async_block_till_done()


async def test_second_entry_aborts(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_sets_weight_jump(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_WEIGHT_JUMP: 1.5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_MAX_WEIGHT_JUMP: 1.5}
    assert entry.runtime_data.tracker.max_weight_jump == 1.5
