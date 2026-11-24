"""Config flow for Clowder: one entry, no settings; one option."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import CONF_MAX_WEIGHT_JUMP, DEFAULT_MAX_WEIGHT_JUMP, DOMAIN


class ClowderConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Clowder", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClowderOptionsFlow()


class ClowderOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_MAX_WEIGHT_JUMP, DEFAULT_MAX_WEIGHT_JUMP)
        schema = vol.Schema(
            {
                vol.Required(CONF_MAX_WEIGHT_JUMP, default=current): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=10)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
