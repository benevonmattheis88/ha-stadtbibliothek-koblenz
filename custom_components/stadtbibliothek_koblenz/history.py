"""Ausleih-Historie: merkt sich jedes gesehene Medium und trägt es bei Verschwinden als zurückgegeben ein.

Bewusst ohne Home-Assistant-Importe, damit es sich allein testen lässt.
"""
from __future__ import annotations

import re
from datetime import date


def _key(loan: dict) -> str:
    ident = (loan.get("barcode") or loan.get("title") or "").replace(" ", "")
    return f"{ident}|{loan.get('loan_date') or ''}"


def update_history(
    hist: dict, loans: list[dict], today: date, expected: int | None = None
) -> list[dict]:
    """Historie mit dem aktuellen Abruf abgleichen. Gibt die neu zurückgegebenen Einträge zurück.

    hist = {"active": {key: eintrag}, "returned": [eintrag, ...]} (neueste zuerst).
    expected = Zahl der Ausleihen laut Kontoübersicht; passt sie nicht zur Liste,
    wurde die Seite wohl nicht vollständig gelesen und es wird nichts als zurückgegeben markiert.
    """
    active: dict = hist.setdefault("active", {})
    returned: list = hist.setdefault("returned", [])
    seen = set()
    for loan in loans:
        key = _key(loan)
        seen.add(key)
        rec = active.get(key)
        if rec is None:
            active[key] = {
                "title": loan.get("title"),
                "author": loan.get("author"),
                "barcode": loan.get("barcode"),
                "format": (loan.get("details") or {}).get("Publikationsform"),
                "branch": loan.get("branch"),
                "loan_date": loan.get("loan_date") or today.isoformat(),
                "due_date": loan.get("due_date"),
                "renewals": 0,
            }
            continue
        due = loan.get("due_date")
        if due and rec.get("due_date") and due > rec["due_date"]:
            rec["renewals"] = rec.get("renewals", 0) + 1
        if due:
            rec["due_date"] = due
    if expected is None and not loans and active:
        # Zähler unbekannt und Liste leer: erst beim zweiten leeren Abruf in Folge
        # glauben, dass wirklich alles zurückgegeben ist
        if not hist.get("leer_gesehen"):
            hist["leer_gesehen"] = True
            return []
    hist.pop("leer_gesehen", None)
    if expected is not None and expected != len(loans):
        return []
    gone = [key for key in active if key not in seen]
    new_returned = []
    for key in gone:
        rec = active.pop(key)
        rec["returned"] = today.isoformat()
        new_returned.append(rec)
    returned[:0] = new_returned
    return new_returned


def expected_count(summary: dict[str, str]) -> int | None:
    """Zahl der Ausleihen aus der Kontoübersicht ("Ausleihen": "7" oder "Entliehene Medien": "7")."""
    for key, value in (summary or {}).items():
        if re.fullmatch(r"ausleihen|entliehene medien|entliehen", key.strip(), re.I):
            digits = "".join(c for c in value if c.isdigit())
            if digits:
                return int(digits)
    return None
