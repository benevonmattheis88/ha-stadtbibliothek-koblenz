# Stadtbibliothek Koblenz für Home Assistant

Liest das Leserkonto im Online-Katalog der Stadtbibliothek Koblenz (Zones, https://stb.koblenz.de/Zones2/) und zeigt die Ausleihen mit Rückgabedatum.

- Einrichtung über *Einstellungen → Geräte & Dienste → Integration hinzufügen → Stadtbibliothek Koblenz*. Ausweisnummer und PIN werden nur in Home Assistant gespeichert.
- Abruf alle 4 Stunden, sofort über den Dienst `stadtbibliothek_koblenz.aktualisieren`.
- Sensoren: `Ausleihen` (Anzahl, Attribut `loans` mit Titel, Verfasser, `due_date`, `days_left`, `renewable`) und `Nächste Rückgabe` (Datum, Attribute `titles`, `days_left`).

Login und Auslesen folgen dem Zones-Backend der Web-Opac-App (opacapp/opacclient).
