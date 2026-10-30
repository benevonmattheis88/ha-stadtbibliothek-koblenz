"""Sensoren: Ausleihen, nächste Rückgabe, Gebühren, Vormerkungen, Ausweis."""
from __future__ import annotations

import re
from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PRIVATE_ROWS
from .entity import _Base


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LoansSensor(coordinator, entry),
            NextDueSensor(coordinator, entry),
            FeesSensor(coordinator, entry),
            ReservationsSensor(coordinator, entry),
            CardValidSensor(coordinator, entry),
        ]
    )


class LoansSensor(_Base, SensorEntity):
    _attr_icon = "mdi:bookshelf"
    _attr_native_unit_of_measurement = "Medien"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "ausleihen")

    @property
    def native_value(self) -> int:
        return len(self._loans)

    @property
    def extra_state_attributes(self) -> dict:
        today = date.today()
        loans = []
        for loan in self._loans:
            item = dict(loan)
            # Tage neu rechnen, damit sie zwischen den Abrufen stimmen
            if item.get("due_date"):
                item["days_left"] = (date.fromisoformat(item["due_date"]) - today).days
            loans.append(item)
        return {
            "loans": loans,
            "overdue_count": sum(1 for l in loans if (l.get("days_left") or 0) < 0),
        }


class NextDueSensor(_Base, SensorEntity):
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "naechste_rueckgabe")

    @property
    def native_value(self) -> date | None:
        dates = [l["due_date"] for l in self._loans if l.get("due_date")]
        return date.fromisoformat(min(dates)) if dates else None

    @property
    def extra_state_attributes(self) -> dict:
        nxt = self.native_value
        if nxt is None:
            return {"titles": [], "days_left": None}
        return {
            "titles": [l["title"] for l in self._loans if l.get("due_date") == nxt.isoformat()],
            "days_left": (nxt - date.today()).days,
        }


class FeesSensor(_Base, SensorEntity):
    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "gebuehren")

    @property
    def native_value(self) -> float | None:
        return self._data.get("fees")

    @property
    def extra_state_attributes(self) -> dict:
        # Kontoübersicht, um das Auslesen prüfen zu können
        rows = self._data.get("summary") or {}
        return {
            "kontouebersicht": {
                k: v for k, v in rows.items() if not re.search(PRIVATE_ROWS, k, re.I)
            }
        }


class ReservationsSensor(_Base, SensorEntity):
    _attr_icon = "mdi:book-clock"
    _attr_native_unit_of_measurement = "Medien"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "vormerkungen")

    @property
    def native_value(self) -> int:
        return len(self._data.get("reservations") or [])

    @property
    def extra_state_attributes(self) -> dict:
        res = self._data.get("reservations") or []
        return {
            "reservations": res,
            "ready_count": sum(1 for r in res if r.get("ready")),
            "ready_titles": [r["title"] for r in res if r.get("ready")],
        }


class CardValidSensor(_Base, SensorEntity):
    _attr_icon = "mdi:card-account-details"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "ausweis_gueltig_bis")

    @property
    def native_value(self) -> date | None:
        v = self._data.get("card_valid_until")
        return date.fromisoformat(v) if v else None

    @property
    def extra_state_attributes(self) -> dict:
        v = self.native_value
        return {"days_left": (v - date.today()).days if v else None}
