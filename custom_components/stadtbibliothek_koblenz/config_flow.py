"""Einrichtung: Ausweisnummer und PIN eingeben, Login wird sofort geprüft."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import LibraryError, LoginFailed, ZonesClient
from .const import CONF_BASE_URL, CONF_CARD, CONF_PIN, DEFAULT_BASE_URL, DOMAIN


class KoblenzLibraryFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _check(self, data: dict[str, Any]) -> str | None:
        try:
            await ZonesClient(data[CONF_BASE_URL], data[CONF_CARD], data[CONF_PIN]).fetch_loans()
        except LoginFailed:
            return "invalid_auth"
        except LibraryError:
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_CARD] = user_input[CONF_CARD].strip()
            await self.async_set_unique_id(user_input[CONF_CARD])
            self._abort_if_unique_id_configured()
            if (err := await self._check(user_input)) is None:
                return self.async_create_entry(
                    title=f"Bibliothek {user_input[CONF_CARD][-4:]}", data=user_input
                )
            errors["base"] = err
        schema = vol.Schema(
            {
                vol.Required(CONF_CARD): str,
                vol.Required(CONF_PIN): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PIN: user_input[CONF_PIN]}
            if (err := await self._check(data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
        )
