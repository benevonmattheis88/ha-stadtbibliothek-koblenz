"""Diagnose-Daten: Ausweisnummer, PIN und persönliche Kontozeilen geschwärzt."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CARD, CONF_PIN, DOMAIN, PRIVATE_ROWS

TO_REDACT = {CONF_CARD, CONF_PIN, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = dict(coordinator.data or {})
    data["summary"] = {
        k: REDACTED if re.search(PRIVATE_ROWS, k, re.I) else v
        for k, v in (data.get("summary") or {}).items()
    }
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "auto_renew": coordinator.auto_renew,
        "data": data,
    }
