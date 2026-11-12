"""Konstanten für Stadtbibliothek Koblenz."""
from datetime import timedelta

DOMAIN = "stadtbibliothek_koblenz"
CONF_CARD = "card_number"
CONF_PIN = "pin"
CONF_BASE_URL = "base_url"
DEFAULT_BASE_URL = "https://stb.koblenz.de/Zones2/"
# Selten abfragen: das eigene Konto ändert sich kaum, die Bibliothek soll nicht belastet werden
UPDATE_INTERVAL = timedelta(hours=4)

# Optionen
CONF_INTERVAL = "update_interval"  # Stunden
DEFAULT_INTERVAL = 4
CONF_RENEW_DAYS = "renew_days_before"  # automatisch verlängern, wenn höchstens so viele Tage übrig
DEFAULT_RENEW_DAYS = 1
EVENT_RENEWED = f"{DOMAIN}_verlaengert"
EVENT_RETURNED = f"{DOMAIN}_zurueckgegeben"
# Zeilen der Kontoübersicht, die persönliche Daten enthalten (nicht als Attribut zeigen)
# Kontozeilen, die in Attribut und Diagnose erscheinen dürfen (alles andere bleibt draußen)
PUBLIC_ROWS = r"ausleihen|entliehen.*|vormerk.*|reserv.*|geb.hr.*|lesegeb.hr|kontostand|saldo|offen.*|dauer|laufzeit|betrag|status|g.ltig.*|ablauf.*|.berf.llig.*|mahn.*"
