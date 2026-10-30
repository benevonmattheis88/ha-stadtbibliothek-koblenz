# Stadtbibliothek Koblenz für Home Assistant

[![Prüfen](https://github.com/benevonmattheis88/ha-stadtbibliothek-koblenz/actions/workflows/validate.yml/badge.svg)](https://github.com/benevonmattheis88/ha-stadtbibliothek-koblenz/actions/workflows/validate.yml)

Liest dein Leserkonto im Online-Katalog der Stadtbibliothek Koblenz (https://stb.koblenz.de/Zones2/) und zeigt Ausleihen mit Rückgabedatum, Vormerkungen, Gebühren und die Gültigkeit des Ausweises. Medien lassen sich aus Home Assistant heraus verlängern, auf Wunsch automatisch kurz vor der Rückgabe.

> **Von Claude geschrieben, von Menschen getestet.** Der Code dieser Integration wurde mit [Claude Code](https://claude.com/claude-code) (KI von Anthropic) geschrieben und von Menschen an einem echten Leserkonto der Stadtbibliothek Koblenz getestet. Welche Funktionen schon im echten Einsatz geprüft sind, steht unter [Teststand](#teststand).

> Kein offizielles Angebot der Stadtbibliothek Koblenz. Die Integration liest die Seiten des Katalogs so, wie sie im Browser erscheinen. Ändert die Bibliothek ihren Katalog, kann das Auslesen ausfallen, bis die Integration angepasst ist.

## Installation

1. In HACS: *Integrationen → ⋮ → Benutzerdefinierte Repositories*, `https://github.com/benevonmattheis88/ha-stadtbibliothek-koblenz` als *Integration* hinzufügen.
2. „Stadtbibliothek Koblenz“ herunterladen und Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Stadtbibliothek Koblenz*, Ausweisnummer und PIN eingeben.

Ausweisnummer und PIN werden nur in Home Assistant gespeichert. Mehrere Ausweise (z. B. für die Familie) lassen sich einzeln hinzufügen.

## Entitäten

| Entität | Inhalt |
|---|---|
| Sensor *Ausleihen* | Anzahl; Attribut `loans` mit `title`, `author`, `barcode`, `due_date`, `days_left`, `renewable`, `renew_note`; `overdue_count` |
| Sensor *Nächste Rückgabe* | Datum; Attribute `titles`, `days_left` |
| Sensor *Gebühren* | offener Betrag in €; Attribut `kontouebersicht` (ohne persönliche Daten) |
| Sensor *Vormerkungen* | Anzahl; Attribute `reservations`, `ready_count`, `ready_titles` |
| Sensor *Ausweis gültig bis* | Datum; Attribut `days_left` |
| Knopf *Alle verlängern* | verlängert alle Medien, die gerade verlängerbar sind |
| Schalter *Automatisch verlängern* | verlängert nach jedem Abruf alle verlängerbaren Medien, die in höchstens X Tagen zurück müssen (Standard: aus) |

## Optionen

Unter *Konfigurieren* bei der Integration:

- **Abruf alle … Stunden** (Standard 4). Bitte nicht zu oft, die Bibliothek soll nicht belastet werden.
- **Automatisch verlängern ab … Tagen vor der Rückgabe** (Standard 1).

## Dienste und Event

- `stadtbibliothek_koblenz.aktualisieren`: Konto sofort lesen.
- `stadtbibliothek_koblenz.verlaengern`: verlängern, optional nur bestimmte `mediennummer`. Gibt `renewed` und `results` zurück.
- Event `stadtbibliothek_koblenz_verlaengert` nach jedem Verlängern, mit `results` und `automatisch` (true beim automatischen Verlängern).

Beispiel: Push aufs Handy nach dem automatischen Verlängern

```yaml
triggers:
  - trigger: event
    event_type: stadtbibliothek_koblenz_verlaengert
    event_data:
      automatisch: true
actions:
  - action: notify.mobile_app_mein_handy
    data:
      title: "Bücherei"
      message: >
        {% for r in trigger.event.data.results %}{{ '✅' if r.success else '❌' }} {{ r.title }}
        {% endfor %}
```

## Teststand

| Funktion | Getestet am echten Konto |
|---|---|
| Anmelden, Ausleihen mit Rückgabedatum | ✅ 30.10.2026 |
| „verlängerbar“ bzw. Grund, warum nicht | ✅ 30.10.2026 |
| Gebühren (0 €), Ausweis gültig bis | ✅ 30.10.2026 |
| Verlängern (Knopf / Dienst) | ⏳ noch offen |
| Automatisch verlängern | ⏳ noch offen |
| Vormerkungen, „abholbereit“ | ⏳ noch offen |
| Gebühren > 0 € | ⏳ noch offen |

## Fehler melden

Bitte ein Issue anlegen und die Diagnose-Daten anhängen (*Geräte & Dienste → Stadtbibliothek Koblenz → ⋮ → Diagnose herunterladen*). Ausweisnummer, PIN, Name und Adresse sind darin geschwärzt.

## Danke

Login und Auslesen folgen dem Zones-Backend der Web-Opac-App ([opacapp/opacclient](https://github.com/opacapp/opacclient)).

---

## English

Home Assistant integration for the public library of Koblenz, Germany (Infor Zones catalogue). Shows loans with due dates, reservations, fees and card validity, and can renew loans, optionally automatically shortly before the due date. Set up via the UI with card number and PIN. Not affiliated with the library. Written by Claude (Anthropic's AI) using Claude Code and tested by humans against a real library account; see *Teststand* above for what has been verified.
