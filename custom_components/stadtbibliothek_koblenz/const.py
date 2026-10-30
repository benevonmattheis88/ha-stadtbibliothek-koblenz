"""Konstanten für Stadtbibliothek Koblenz."""
from datetime import timedelta

DOMAIN = "stadtbibliothek_koblenz"
CONF_CARD = "card_number"
CONF_PIN = "pin"
CONF_BASE_URL = "base_url"
DEFAULT_BASE_URL = "https://stb.koblenz.de/Zones2/"
# Selten abfragen: das eigene Konto ändert sich kaum, die Bibliothek soll nicht belastet werden
UPDATE_INTERVAL = timedelta(hours=4)
