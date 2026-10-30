"""Knopf: alle gerade verlängerbaren Medien verlängern."""
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import _Base


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RenewAllButton(hass.data[DOMAIN][entry.entry_id], entry)])


class RenewAllButton(_Base, ButtonEntity):
    _attr_icon = "mdi:book-refresh"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "alle_verlaengern")

    async def async_press(self) -> None:
        results = await self.coordinator.async_renew()
        if not results:
            text = "Gerade lässt sich nichts verlängern."
        else:
            text = "\n".join(
                f"{'✅' if r['success'] else '❌'} {r['title']}"
                + ("" if r["success"] else f" ({r['message']})")
                for r in results
            )
        persistent_notification.async_create(
            self.hass, text, title="Bücherei: Verlängern", notification_id=f"{DOMAIN}_verlaengern"
        )
