"""Gemeinsame Basis aller Entitäten (ein Gerät pro Leserkonto)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class _Base(CoordinatorEntity):
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
    def _data(self) -> dict:
        return self.coordinator.data or {}

    @property
    def _loans(self) -> list[dict]:
        return self._data.get("loans") or []
