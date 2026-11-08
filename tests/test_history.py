"""Tests für die Ausleih-Historie."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "stadtbibliothek_koblenz" / "history.py"
_spec = importlib.util.spec_from_file_location("zones_history", _PATH)
history = importlib.util.module_from_spec(_spec)
sys.modules["zones_history"] = history
_spec.loader.exec_module(history)

A = {"title": "Buch A", "barcode": "M86 1", "loan_date": "2026-10-30", "due_date": "2026-11-13",
     "details": {"Publikationsform": "BUC"}}
B = {"title": "Film B", "barcode": "M86 2", "loan_date": "2026-10-30", "due_date": "2026-11-13"}


def test_new_loans_are_tracked_and_returns_recorded():
    h = {}
    assert history.update_history(h, [A, B], date(2026, 11, 1), expected=2) == []
    assert len(h["active"]) == 2
    gone = history.update_history(h, [A], date(2026, 11, 5), expected=1)
    assert [r["title"] for r in gone] == ["Film B"]
    assert gone[0]["returned"] == "2026-11-05"
    assert h["returned"][0]["title"] == "Film B"
    assert list(h["active"].values())[0]["format"] == "BUC"


def test_renewal_is_counted():
    h = {}
    history.update_history(h, [A], date(2026, 11, 1))
    history.update_history(h, [{**A, "due_date": "2026-12-11"}], date(2026, 11, 12))
    history.update_history(h, [], date(2026, 12, 10))
    assert h["returned"][0]["renewals"] == 1
    assert h["returned"][0]["due_date"] == "2026-12-11"


def test_incomplete_list_does_not_mark_returned():
    h = {}
    history.update_history(h, [A, B], date(2026, 11, 1))
    assert history.update_history(h, [A], date(2026, 11, 2), expected=2) == []
    assert len(h["active"]) == 2


def test_same_item_borrowed_again_is_new_entry():
    h = {}
    history.update_history(h, [A], date(2026, 11, 1))
    history.update_history(h, [], date(2026, 11, 10))
    history.update_history(h, [{**A, "loan_date": "2027-01-05"}], date(2027, 1, 5))
    assert len(h["returned"]) == 1 and len(h["active"]) == 1


def test_expected_count():
    assert history.expected_count({"Ausleihen": "7"}) == 7
    assert history.expected_count({}) is None
