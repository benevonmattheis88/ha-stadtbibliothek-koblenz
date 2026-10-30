"""Stadtbibliothek Koblenz: Ausleihen und Rückgabedaten aus dem Leserkonto."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import LoansCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = LoansCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: hass.async_create_task(coordinator.async_auto_renew())
        )
    )
    entry.async_on_unload(entry.add_update_listener(_options_changed))

    if not hass.services.has_service(DOMAIN, "aktualisieren"):
        async def _refresh(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                await coord.async_request_refresh()

        hass.services.async_register(DOMAIN, "aktualisieren", _refresh)

        async def _renew(call: ServiceCall) -> ServiceResponse:
            nummern = call.data.get("mediennummer") or None
            results: list[dict] = []
            for coord in hass.data.get(DOMAIN, {}).values():
                results += await coord.async_renew(nummern)
            return {"renewed": sum(1 for r in results if r["success"]), "results": results}

        hass.services.async_register(
            DOMAIN,
            "verlaengern",
            _renew,
            schema=vol.Schema({vol.Optional("mediennummer"): vol.All(cv.ensure_list, [cv.string])}),
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def _options_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
