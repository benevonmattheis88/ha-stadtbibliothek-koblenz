"""Zugriff auf das Leserkonto im Zones-Katalog der Stadtbibliothek Koblenz.

Ablauf wie im Zones-Backend der Web-Opac-App (opacapp/opacclient, Zones.java):
1. GET  {base}/APS_ZONES?fn=MyZone&Style=Portal3&SubStyle=&Lang=GER&ResponseEncoding=utf-8
2. POST #LoginForm mit BRWR (Ausweisnummer) und PIN
3. Link "Entliehene Medien" / "Ausleihen" folgen und die Liste auslesen
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

MYZONE_QUERY = "APS_ZONES?fn=MyZone&Style=Portal3&SubStyle=&Lang=GER&ResponseEncoding=utf-8"
TIMEOUT = aiohttp.ClientTimeout(total=45)
HEADERS = {"User-Agent": "HomeAssistant-Stadtbibliothek-Koblenz/0.1"}
DUE_LABEL = re.compile(r"f.lligkeit|f.llig|leihfrist|frist|r.ckgabe", re.I)
# Felder mit Datum, die nicht das Rückgabedatum sind
NOT_DUE_LABEL = re.compile(r"ausgeliehen|entliehen|ausleih|seit|vorgemerkt", re.I)
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
MAX_PAGES = 10
RENEW_RE = re.compile(r"renewItem\('[0-9]+',\s*'(.*?)'\)")
CANNOT_RENEW_RE = re.compile(r"CannotRenewLoan\('[0-9]+',\s*'(.*?)'")


class LibraryError(Exception):
    """Katalog nicht erreichbar oder Seite unerwartet aufgebaut."""


class LoginFailed(LibraryError):
    """Ausweisnummer oder PIN falsch."""


@dataclass
class Loan:
    title: str
    author: str | None
    due_date: str | None  # ISO-Datum
    days_left: int | None
    renewable: bool | None
    barcode: str | None
    branch: str | None
    details: dict[str, str]
    renew_note: str | None


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    day, month, year = (int(x) for x in m.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _find_login_form(html: str):
    soup = BeautifulSoup(html, "html.parser")
    return soup, soup.find("form", id="LoginForm")


def _is_logged_in(soup) -> bool:
    return soup.select_one(".AccountSummaryCounterLink") is not None


def _find_lent_link(soup) -> str | None:
    # Kontoübersicht: Zeile "Entliehene Medien" mit Link
    for cell in soup.select(".AccountSummaryCounterNameCell, .AccountSummaryCounterLink"):
        if "Entliehene Medien" in _text(cell):
            a = cell if cell.name == "a" else cell.find("a", href=True)
            if a is None and cell.parent is not None:
                a = cell.parent.find("a", href=True)
            if a is not None and a.get("href"):
                return a["href"]
    for a in soup.select("a.AccountMenuLink[href]"):
        if "Ausleihen" in _text(a):
            return a["href"]
    for a in soup.find_all("a", href=True):
        if "Entliehene Medien" in _text(a):
            return a["href"]
    return None



AMOUNT_RE = re.compile(r"(-?\d+[.,]\d{2})\s*(?:€|EUR)", re.I)
VALID_RE = re.compile(r"(?:g.ltig|ablauf|l.uft ab|verfall)[^0-9]{0,40}(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I)


def _summary(soup) -> dict[str, str]:
    """Zeilen der Kontoübersicht als Name -> Wert (für Gebühren, Ausweis, Zähler)."""
    rows: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = [_text(td) for td in tr.find_all(["td", "th"], recursive=False)]
        cells = [c for c in cells if c]
        if 2 <= len(cells) <= 3 and len(cells[0]) < 60 and not tr.find("table"):
            rows.setdefault(cells[0].rstrip(":"), " ".join(cells[1:])[:120])
    return rows


def _fees(soup, rows: dict[str, str]) -> float | None:
    for k, v in rows.items():
        if re.search(r"kontostand|geb.hr|saldo|offen", k, re.I):
            if m := AMOUNT_RE.search(v) or re.search(r"(-?\d+[.,]\d{2})", v):
                return abs(float(m.group(1).replace(",", ".")))
    text = _text(soup)
    i = text.lower().find("kontostand")
    if i >= 0 and (m := AMOUNT_RE.search(text[i : i + 80])):
        return abs(float(m.group(1).replace(",", ".")))
    return None


def _card_valid_until(soup, rows: dict[str, str]) -> date | None:
    for k, v in rows.items():
        if re.search(r"g.ltig|ablauf|verfall", k, re.I) and (d := _parse_date(v)):
            return d
    if m := VALID_RE.search(_text(soup)):
        return _parse_date(m.group(1))
    return None


def _find_reservations_link(soup) -> str | None:
    for a in soup.find_all("a", href=True):
        t = _text(a)
        if re.search(r"vormerk|reserv", t, re.I) and "BACNO" not in a["href"]:
            return a["href"]
    for cell in soup.select(".AccountSummaryCounterNameCell"):
        if re.search(r"vormerk|reserv", _text(cell), re.I):
            a = cell.find("a", href=True) or (cell.parent.find("a", href=True) if cell.parent else None)
            if a:
                return a["href"]
    return None


def _parse_reservations(soup) -> list[dict]:
    out: list[dict] = []
    for table in soup.select(
        ".MessageBrowseItemDetailsCellStripe table, .MessageBrowseItemDetailsCell table"
    ):
        fields: dict[str, str] = {}
        for tr in table.find_all("tr"):
            name = tr.select_one("[class*=FieldNameCell]")
            data = tr.select_one("[class*=FieldDataCell]")
            if name is not None and data is not None:
                fields[_text(name).rstrip(":")] = _text(data)
        title = fields.get("Titel")
        if not title:
            continue
        text = " ".join(fields.values()) + " " + _text(table)
        out.append(
            {
                "title": title,
                "author": fields.get("Verfasser"),
                "ready": bool(re.search(r"abhol|liegt bereit|bereitgestellt|eingetroffen", text, re.I)),
                "details": {k: v for k, v in fields.items() if k and k != "Titel"},
            }
        )
    return out

def _parse_loans(soup, today: date) -> list[tuple[Loan, str | None]]:
    """Medien der Seite, jeweils mit dem Pfad zum Verlängern (falls möglich)."""
    loans: list[Loan] = []
    renew_paths: list[str | None] = []
    for table in soup.select(
        ".LoansBrowseItemDetailsCellStripe table, .LoansBrowseItemDetailsCell table"
    ):
        fields: dict[str, str] = {}
        for tr in table.find_all("tr"):
            name = tr.select_one(".LoanBrowseFieldNameCell")
            data = tr.select_one(".LoanBrowseFieldDataCell")
            if name is not None and data is not None:
                fields[_text(name).rstrip(":")] = _text(data)
        title = fields.get("Titel")
        if not title:
            continue
        due = None
        for k, v in fields.items():
            if DUE_LABEL.search(k) and (due := _parse_date(v)):
                break
        if due is None:
            # Kein passendes Feld gefunden: erstes Datum, das kein Ausleihdatum ist
            for k, v in fields.items():
                if not NOT_DUE_LABEL.search(k) and (due := _parse_date(v)):
                    break
        if due is None:
            # Datum steht außerhalb der Feldzeilen: spätestes Datum im Block nehmen
            found = [_parse_date(m.group(0)) for m in DATE_RE.finditer(_text(table))]
            found = [d for d in found if d]
            due = max(found) if found else None
        # Wie in Zones.java: renewItem(..) = verlängerbar, CannotRenewLoan(..'Grund'..) = gerade nicht
        renew_path = None
        renew_note = None
        renewable: bool | None = None
        for x in table.find_all("a", href=True):
            if m := RENEW_RE.search(x["href"]):
                renew_path, renewable = m.group(1), True
                break
            if m := CANNOT_RENEW_RE.search(x["href"]):
                renewable, renew_note = False, m.group(1).strip()
        loans.append(
            Loan(
                title=title,
                author=fields.get("Verfasser"),
                due_date=due.isoformat() if due else None,
                days_left=(due - today).days if due else None,
                renewable=renewable,
                barcode=fields.get("Mediennummer"),
                branch=fields.get("ausgeliehen in"),
                details={k: v for k, v in fields.items() if k and k != "Titel"},
                renew_note=renew_note,
            )
        )
        renew_paths.append(renew_path)
    return list(zip(loans, renew_paths))


def _next_page(soup) -> str | None:
    for a in soup.select("a.pageNavLink[href]"):
        if "nächsten" in (a.get("title") or ""):
            return a["href"]
    return None


class ZonesClient:
    """Ein Abruf = neue Sitzung: einloggen, Ausleihen lesen, fertig."""

    def __init__(self, base_url: str, card: str, pin: str) -> None:
        self._base = base_url.rstrip("/") + "/"
        self._card = card
        self._pin = pin

    async def fetch_loans(self) -> dict:
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(), timeout=TIMEOUT, headers=HEADERS
            ) as session:
                return await self._fetch(session)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LibraryError(f"Katalog nicht erreichbar: {err}") from err

    async def _get(self, session, url: str) -> tuple[str, str]:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.text(errors="replace"), str(resp.url)

    async def _prefixes(self, session) -> list[str]:
        """Mögliche Pfade vor 'APS_ZONES' (je nach Zones-Version verschieden)."""
        found: list[str] = []
        try:
            html, page_url = await self._get(session, self._base)
            for m in re.finditer(r"""["']([^"'\s]*?)APS_ZONES""", html):
                found.append(urljoin(page_url, m.group(1) or "./"))
        except aiohttp.ClientResponseError:
            pass
        found += [self._base, urljoin(self._base, "alswww2.dll/")]
        return list(dict.fromkeys(found))

    async def _login(self, session):
        """Einloggen, liefert die Kontoseite (soup) und ihre Adresse."""
        loop = asyncio.get_running_loop()
        soup = form = None
        page_url = self._base
        for prefix in await self._prefixes(session):
            try:
                html, page_url = await self._get(session, urljoin(prefix, MYZONE_QUERY))
            except aiohttp.ClientResponseError:
                continue
            soup, form = await loop.run_in_executor(None, _find_login_form, html)
            if form is not None or _is_logged_in(soup):
                break

        if soup is None or not _is_logged_in(soup):
            if form is None:
                raise LibraryError("Anmeldeformular nicht gefunden")
            data = {
                i["name"]: i.get("value", "")
                for i in form.find_all("input")
                if i.get("name") and i["name"] not in ("BRWR", "PIN")
            }
            data["BRWR"] = self._card
            data["PIN"] = self._pin
            action = urljoin(page_url, form.get("action") or page_url)
            async with session.post(action, data=data) as resp:
                resp.raise_for_status()
                html = await resp.text(errors="replace")
                page_url = str(resp.url)
            if "Kontostand" not in html:
                raise LoginFailed("Anmeldung fehlgeschlagen")
            soup = await loop.run_in_executor(None, BeautifulSoup, html, "html.parser")
        return soup, page_url

    async def _loan_items(self, session) -> list[tuple[Loan, str | None]]:
        loop = asyncio.get_running_loop()
        soup, page_url = await self._login(session)
        self._account = (soup, page_url)
        link = _find_lent_link(soup)
        if link is None:
            # Konto ohne Ausleihen zeigt keinen Link
            return []
        url = urljoin(page_url, link.replace("utf-8?Method", "utf-8&Method"))

        today = datetime.now().date()
        items: list[tuple[Loan, str | None]] = []
        for _ in range(MAX_PAGES):
            html, page_url = await self._get(session, url)
            soup = await loop.run_in_executor(None, BeautifulSoup, html, "html.parser")
            items.extend(
                (loan, urljoin(page_url, path) if path else None)
                for loan, path in _parse_loans(soup, today)
            )
            nxt = _next_page(soup)
            if not nxt:
                break
            url = urljoin(page_url, nxt)
        return items

    async def _fetch(self, session) -> dict:
        loop = asyncio.get_running_loop()
        loans = [loan for loan, _ in await self._loan_items(session)]
        loans.sort(key=lambda l: l.due_date or "9999-12-31")
        soup, page_url = self._account  # Kontoübersicht aus dem Login
        rows = _summary(soup)
        valid = _card_valid_until(soup, rows)
        reservations: list[dict] = []
        if link := _find_reservations_link(soup):
            url = urljoin(page_url, link.replace("utf-8?Method", "utf-8&Method"))
            try:
                html, _ = await self._get(session, url)
                rsoup = await loop.run_in_executor(None, BeautifulSoup, html, "html.parser")
                reservations = _parse_reservations(rsoup)
            except aiohttp.ClientResponseError:
                pass
        return {
            "loans": [asdict(l) for l in loans],
            "fees": _fees(soup, rows),
            "card_valid_until": valid.isoformat() if valid else None,
            "reservations": reservations,
            "summary": rows,
        }

    async def renew(self, barcodes: list[str] | None = None) -> list[dict]:
        """Verlängert die genannten Medien (Mediennummer), ohne Angabe alle verlängerbaren."""
        wanted = {b.replace(" ", "") for b in barcodes} if barcodes else None
        results: list[dict] = []
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(), timeout=TIMEOUT, headers=HEADERS
            ) as session:
                for loan, url in await self._loan_items(session):
                    if wanted is not None and (loan.barcode or "").replace(" ", "") not in wanted:
                        continue
                    result = {"title": loan.title, "barcode": loan.barcode}
                    if url is None:
                        if wanted is None:
                            continue  # "alle" heißt: alle, die gerade verlängerbar sind
                        results.append({**result, "success": False,
                                        "message": loan.renew_note or "nicht verlängerbar"})
                        continue
                    html, _ = await self._get(session, url)
                    soup = BeautifulSoup(html, "html.parser")
                    box = soup.select_one("#SSRenewDlgContent")
                    text = _text(box) if box else _text(soup)[:300]
                    results.append({**result, "success": "erfolgreich" in text.lower(),
                                    "message": text[:300]})
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise LibraryError(f"Katalog nicht erreichbar: {err}") from err
        return results
