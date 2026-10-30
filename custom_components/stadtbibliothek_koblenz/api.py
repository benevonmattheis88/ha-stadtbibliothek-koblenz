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


def _parse_loans(soup, today: date) -> list[Loan]:
    loans: list[Loan] = []
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
        # Wie in Zones.java: Verlängern-Knöpfe stehen in der Tabelle des Mediums
        if table.select_one(".CannotRenewLink"):
            renewable: bool | None = False
        elif table.select_one(".button[title*=Zum], a[href*=renewItem]"):
            renewable = True
        else:
            renewable = None
        loans.append(
            Loan(
                title=title,
                author=fields.get("Verfasser"),
                due_date=due.isoformat() if due else None,
                days_left=(due - today).days if due else None,
                renewable=renewable,
                barcode=fields.get("Mediennummer"),
                branch=fields.get("ausgeliehen in"),
                details={k: v for k, v in fields.items() if k != "Titel"},
            )
        )
    return loans


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

    async def fetch_loans(self) -> list[dict]:
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

    async def _fetch(self, session) -> list[dict]:
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

        link = _find_lent_link(soup)
        if link is None:
            # Konto ohne Ausleihen zeigt keinen Link
            return []
        url = urljoin(page_url, link.replace("utf-8?Method", "utf-8&Method"))

        today = datetime.now().date()
        loans: list[Loan] = []
        for _ in range(MAX_PAGES):
            html, page_url = await self._get(session, url)
            soup = await loop.run_in_executor(None, BeautifulSoup, html, "html.parser")
            loans.extend(_parse_loans(soup, today))
            nxt = _next_page(soup)
            if not nxt:
                break
            url = urljoin(page_url, nxt)

        loans.sort(key=lambda l: l.due_date or "9999-12-31")
        return [asdict(l) for l in loans]
