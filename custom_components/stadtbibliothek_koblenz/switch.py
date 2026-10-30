"""Schalter: bald fällige Medien automatisch verlängern."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import _Base


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AutoRenewSwitch(hass.data[DOMAIN][entry.entry_id], entry)])


class AutoRenewSwitch(_Base, SwitchEntity, RestoreEntity):
    _attr_icon = "mdi:book-sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "automatisch_verlaengern")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.coordinator.auto_renew = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_renew

    @property
    def extra_state_attributes(self) -> dict:
        return {"tage_vorher": self.coordinator.renew_days}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.auto_renew = True
        self.async_write_ha_state()
        await self.coordinator.async_auto_renew()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.auto_renew = False
        self.async_write_ha_state()
