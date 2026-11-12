"""Abruf des Leserkontos, Verlängern und automatisches Verlängern."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LibraryError, LoginFailed, RenewInterrupted, ZonesClient
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
    EVENT_RETURNED,
)
from .history import expected_count, update_history

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
        self._login_failures = 0  # erst beim zweiten Fehlschlag in Folge neu anmelden lassen
        self._renew_lock = asyncio.Lock()  # nie zwei Verlängerungen gleichzeitig
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.historie_{entry.entry_id}")
        self.history: dict = {"active": {}, "returned": []}

    async def async_load_history(self) -> None:
        if stored := await self._store.async_load():
            self.history = stored

    async def _async_update_data(self) -> dict:
        try:
            data = await self.client.fetch_loans()
        except LoginFailed as err:
            # Eine Fehlerseite mit Anmeldeformular im Kopf sieht aus wie eine falsche PIN.
            # Darum erst beim zweiten Mal in Folge die Neuanmeldung verlangen.
            self._login_failures += 1
            if self._login_failures >= 2:
                raise ConfigEntryAuthFailed(str(err)) from None
            raise UpdateFailed(f"{err}, nächster Versuch beim nächsten Abruf") from None
        except LibraryError as err:
            raise UpdateFailed(str(err)) from None
        self._login_failures = 0
        before = repr(self.history)
        returned = update_history(
            self.history, data["loans"], date.today(), expected_count(data.get("summary"))
        )
        if repr(self.history) != before:
            self._save()
        for rec in returned:
            self.hass.bus.async_fire(EVENT_RETURNED, dict(rec))
        return data

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.history, 10)

    @property
    def _auto_log(self) -> dict[str, dict]:
        """Pro Mediennummer: für welches Rückgabedatum zuletzt automatisch versucht, und wann."""
        return self.history.setdefault("auto_versucht", {})

    async def async_renew(
        self, barcodes: list[str] | None = None, automatic: bool = False
    ) -> list[dict]:
        """Verlängern, danach Konto neu lesen und Ergebnis melden (auch Teilergebnisse)."""
        async with self._renew_lock:
            return await self._renew(barcodes, automatic)

    async def _renew(self, barcodes: list[str] | None, automatic: bool) -> list[dict]:
        error: str | None = None
        try:
            results = await self.client.renew(barcodes)
        except LoginFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except RenewInterrupted as err:
            results, error = err.results, str(err)
        except LibraryError as err:
            raise HomeAssistantError(str(err)) from None
        if automatic:
            today = date.today().isoformat()
            due = {l.get("barcode"): l.get("due_date") for l in (self.data or {}).get("loans") or []}
            for r in results:  # nur Medien, für die die Bibliothek geantwortet hat
                if r.get("barcode"):
                    self._auto_log[r["barcode"]] = {
                        "rueckgabe": due.get(r["barcode"]), "am": today, "ok": r["success"]
                    }
            self._save()
        await self.async_request_refresh()
        self.hass.bus.async_fire(EVENT_RENEWED, {"results": results, "automatisch": automatic})
        if error:
            if automatic:
                notify_results(self.hass, results, "Bücherei: automatisch verlängert (abgebrochen)")
            raise HomeAssistantError(f"Verlängern abgebrochen: {error}")
        return results

    def due_for_auto_renew(self, today: date | None = None) -> list[str]:
        """Mediennummern, die bald fällig, verlängerbar und für dieses Datum noch nicht versucht sind."""
        today = today or date.today()
        out = []
        for loan in (self.data or {}).get("loans") or []:
            barcode, due = loan.get("barcode"), loan.get("due_date")
            if not (loan.get("renewable") and barcode and due):
                continue
            if (date.fromisoformat(due) - today).days > self.renew_days:
                continue
            last = self._auto_log.get(barcode) or {}
            if not last.get("ok"):
                if last.get("am") == today.isoformat():
                    continue  # nach einer Absage erst morgen wieder
            elif last.get("rueckgabe") == due:
                continue  # für dieses Rückgabedatum schon erfolgreich verlängert
            elif last.get("am") and date.fromisoformat(due) > today:
                # nach einem Erfolg frühestens wieder, wenn das Fenster neu erreicht ist
                # (verhindert tägliches Verlängern bei sehr kurzer Leihfrist);
                # am Fälligkeitstag selbst immer, damit nichts überfällig wird
                if (today - date.fromisoformat(last["am"])).days < self.renew_days:
                    continue
            out.append(barcode)
        return out

    async def async_auto_renew(self) -> None:
        """Nach jedem Abruf: fällige Medien verlängern, wenn der Schalter an ist."""
        if not self.auto_renew or self._renew_lock.locked():
            return
        async with self._renew_lock:
            if not (wanted := self.due_for_auto_renew()):
                return
            try:
                results = await self._renew(wanted, automatic=True)
            except HomeAssistantError as err:
                _LOGGER.warning("Automatisches Verlängern fehlgeschlagen: %s", err)
                return
            notify_results(self.hass, results, "Bücherei: automatisch verlängert")
