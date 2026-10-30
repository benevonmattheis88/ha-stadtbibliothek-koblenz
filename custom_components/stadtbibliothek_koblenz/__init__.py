"""Stadtbibliothek Koblenz: Ausleihen und Rückgabedaten aus dem Leserkonto."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LibraryError, LoginFailed, ZonesClient
from .const import CONF_BASE_URL, CONF_CARD, CONF_PIN, DEFAULT_BASE_URL, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


class LoansCoordinator(DataUpdateCoordinator[list[dict]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.client = ZonesClient(
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.data[CONF_CARD],
            entry.data[CONF_PIN],
        )

    async def async_renew(self, barcodes: list[str] | None = None) -> list[dict]:
        """Verlängern, danach Konto neu lesen und Ergebnis melden."""
        try:
            results = await self.client.renew(barcodes)
        except LoginFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        self.hass.bus.async_fire(f"{DOMAIN}_verlaengert", {"results": results})
        return results

    async def _async_update_data(self) -> list[dict]:
        try:
            return await self.client.fetch_loans()
        except LoginFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise UpdateFailed(str(err)) from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = LoansCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
