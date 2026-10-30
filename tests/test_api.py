"""Tests für das Auslesen des Zones-Katalogs gegen einen kleinen Testserver."""
import asyncio
import importlib.util
import sys
from pathlib import Path

from aiohttp import web
from bs4 import BeautifulSoup

_PATH = Path(__file__).parents[1] / "custom_components" / "stadtbibliothek_koblenz" / "api.py"
_spec = importlib.util.spec_from_file_location("zones_api", _PATH)
api = importlib.util.module_from_spec(_spec)
sys.modules["zones_api"] = api
_spec.loader.exec_module(api)

ACCOUNT = """<table>
<tr><td>Gebühren</td><td>€ 2,50</td></tr>
<tr><td>Name</td><td>Erika Mustermann</td></tr>
<tr><td>Lesegebühr</td><td>Normal Jährlich</td></tr>
<tr><td>Dauer</td><td>11/08/2026 bis 10/08/2027</td></tr>
</table>
<a href="APS_PRESENT_BIB?Style=Portal3&ResponseEncoding=utf-8?Method=ShowReservations">Vormerkungen</a>
<table><tr><td class="AccountSummaryCounterNameCell"><a href="APS_PRESENT_BIB?Style=Portal3&ResponseEncoding=utf-8?Method=ShowLoans">Entliehene Medien</a></td></tr></table>
<div class="LoansBrowseItemDetailsCellStripe"><table>
<tr><td class="LoanBrowseFieldNameCell">Titel</td><td class="LoanBrowseFieldDataCell">Buch A</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Verfasser</td><td class="LoanBrowseFieldDataCell">Autorin X</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Mediennummer</td><td class="LoanBrowseFieldDataCell">M86 1</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Ausleih- Datum</td><td class="LoanBrowseFieldDataCell">30.10.2026</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Rückgabe- Datum</td><td class="LoanBrowseFieldDataCell">13.11.2026 <a href="javascript:renewItem('1','APS_ZONES?fn=Renew&amp;X=1')">Verlängern</a></td></tr>
</table></div>
<div class="LoansBrowseItemDetailsCell"><table>
<tr><td class="LoanBrowseFieldNameCell">Titel</td><td class="LoanBrowseFieldDataCell">Film B</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Mediennummer</td><td class="LoanBrowseFieldDataCell">M86 2</td></tr>
<tr><td class="LoanBrowseFieldNameCell">Rückgabe- Datum</td><td class="LoanBrowseFieldDataCell">20.11.2026 <a href="javascript:CannotRenewLoan('2','das Medium wurde heute schon verlängert','0')">?</a></td></tr>
</table></div>"""

RESERVATIONS = """<div class="MessageBrowseItemDetailsCell"><table>
<tr><td>Titel</td><td>Gregs Tagebuch</td></tr><tr><td>Status</td><td>Liegt zur Abholung bereit</td></tr>
</table></div>
<div class="MessageBrowseItemDetailsCellStripe"><table>
<tr><td>Titel</td><td>Der Hobbit</td></tr><tr><td>Status</td><td>Position 3</td></tr>
</table></div>"""


def _html(text):
    return web.Response(text=text, content_type="text/html")


async def _server():
    async def root(request):
        return _html('<a href="alswww2.dll/APS_ZONES?fn=Search">Suche</a>')

    async def zones(request):
        if request.query.get("fn") == "Renew":
            assert request.query.get("X") == "1"
            return _html('<div id="SSRenewDlgContent">Verlängerung erfolgreich</div>')
        return _html(
            '<form id="LoginForm" action="APS_ZONES?fn=Login">'
            '<input name="BRWR"><input name="PIN"></form>'
        )

    async def login(request):
        form = await request.post()
        if form.get("PIN") != "1234":
            return _html('<form id="LoginForm"><input name="BRWR"></form>')
        return _html("Kontostand " + ACCOUNT)

    async def present(request):
        if request.query.get("Method") == "ShowReservations":
            return _html(RESERVATIONS)
        return _html(ACCOUNT)

    app = web.Application()
    app.router.add_get("/Zones2/", root)
    app.router.add_get("/Zones2/alswww2.dll/APS_ZONES", zones)
    app.router.add_post("/Zones2/alswww2.dll/APS_ZONES", login)
    app.router.add_get("/Zones2/alswww2.dll/APS_PRESENT_BIB", present)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/Zones2/"


def _run(coro_fn, pin="1234"):
    async def main():
        runner, url = await _server()
        try:
            return await coro_fn(api.ZonesClient(url, "4711", pin))
        finally:
            await runner.cleanup()

    return asyncio.run(main())


def test_fetch_account():
    data = _run(lambda c: c.fetch_loans())
    loans = {l["title"]: l for l in data["loans"]}
    assert loans["Buch A"]["due_date"] == "2026-11-13"
    assert loans["Buch A"]["renewable"] is True
    assert loans["Buch A"]["author"] == "Autorin X"
    assert loans["Film B"]["renewable"] is False
    assert "heute schon verlängert" in loans["Film B"]["renew_note"]
    assert data["fees"] == 2.5
    assert data["card_valid_until"] == "2027-08-10"
    ready = [r["title"] for r in data["reservations"] if r["ready"]]
    assert ready == ["Gregs Tagebuch"]
    assert len(data["reservations"]) == 2


def test_renew_all_skips_not_renewable():
    results = _run(lambda c: c.renew())
    assert [(r["title"], r["success"]) for r in results] == [("Buch A", True)]


def test_renew_named_item_reports_reason():
    results = _run(lambda c: c.renew(["M86 2"]))
    assert results[0]["success"] is False
    assert "heute schon verlängert" in results[0]["message"]


def test_wrong_pin():
    try:
        _run(lambda c: c.fetch_loans(), pin="0000")
    except api.LoginFailed:
        return
    raise AssertionError("LoginFailed erwartet")


def test_parse_date():
    assert str(api._parse_date("13.11.26")) == "2026-11-13"
    assert api._parse_date("kein Datum") is None


def test_card_valid_until_from_label():
    soup = BeautifulSoup("<p></p>", "html.parser")
    assert str(api._card_valid_until(soup, {"Ausweis gültig bis": "31.03.2027"})) == "2027-03-31"
