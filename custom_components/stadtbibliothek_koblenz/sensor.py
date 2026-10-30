"""Sensoren: Anzahl Ausleihen (mit Liste) und nächste Rückgabe."""
from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LoansSensor(coordinator, entry), NextDueSensor(coordinator, entry)])


class _Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="Stadtbibliothek Koblenz",
            manufacturer="Stadtbibliothek Koblenz",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _loans(self) -> list[dict]:
        return self.coordinator.data or []


class LoansSensor(_Base):
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


class NextDueSensor(_Base):
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
