"""Abruf des Leserkontos, Verlängern und automatisches Verlängern."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LibraryError, LoginFailed, ZonesClient
from .const import (
    CONF_BASE_URL,
    CONF_CARD,
    CONF_INTERVAL,
    CONF_PIN,
    CONF_RENEW_DAYS,
    DEFAULT_BASE_URL,
    DEFAULT_INTERVAL,
    DEFAULT_RENEW_DAYS,
    DOMAIN,
    EVENT_RENEWED,
)

_LOGGER = logging.getLogger(__name__)


def notify_results(hass: HomeAssistant, results: list[dict], title: str) -> None:
    """Ergebnis eines Verlängerns als Mitteilung in Home Assistant."""
    if not results:
        text = "Gerade lässt sich nichts verlängern."
    else:
        text = "\n".join(
            f"{'✅' if r['success'] else '❌'} {r['title']}"
            + ("" if r["success"] else f" ({r['message']})")
            for r in results
        )
    persistent_notification.async_create(
        hass, text, title=title, notification_id=f"{DOMAIN}_verlaengern"
    )


class LoansCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        hours = entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(hours=hours))
        self.client = ZonesClient(
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.data[CONF_CARD],
            entry.data[CONF_PIN],
        )
        self.renew_days: int = entry.options.get(CONF_RENEW_DAYS, DEFAULT_RENEW_DAYS)
        self.auto_renew = False  # setzt der Schalter
        self._auto_tried: dict[str, date] = {}  # pro Medium höchstens ein Versuch am Tag
        self._auto_running = False

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.fetch_loans()
        except LoginFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise UpdateFailed(str(err)) from err

    async def async_renew(
        self, barcodes: list[str] | None = None, automatic: bool = False
    ) -> list[dict]:
        """Verlängern, danach Konto neu lesen und Ergebnis melden."""
        try:
            results = await self.client.renew(barcodes)
        except LoginFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LibraryError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        self.hass.bus.async_fire(EVENT_RENEWED, {"results": results, "automatisch": automatic})
        return results

    def due_for_auto_renew(self, today: date | None = None) -> list[str]:
        """Mediennummern, die bald fällig, verlängerbar und heute noch nicht versucht sind."""
        today = today or date.today()
        out = []
        for loan in (self.data or {}).get("loans") or []:
            barcode, due = loan.get("barcode"), loan.get("due_date")
            if not (loan.get("renewable") and barcode and due):
                continue
            if (date.fromisoformat(due) - today).days > self.renew_days:
                continue
            if self._auto_tried.get(barcode) == today:
                continue
            out.append(barcode)
        return out

    async def async_auto_renew(self) -> None:
        """Nach jedem Abruf: fällige Medien verlängern, wenn der Schalter an ist."""
        if not self.auto_renew or self._auto_running:
            return
        if not (wanted := self.due_for_auto_renew()):
            return
        self._auto_running = True
        try:
            today = date.today()
            for barcode in wanted:
                self._auto_tried[barcode] = today
            try:
                results = await self.async_renew(wanted, automatic=True)
            except HomeAssistantError as err:
                _LOGGER.warning("Automatisches Verlängern fehlgeschlagen: %s", err)
                return
            notify_results(self.hass, results, "Bücherei: automatisch verlängert")
        finally:
            self._auto_running = False
