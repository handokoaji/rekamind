from datetime import date

import pytest

from rekamind_server.deadlines import resolve_deadline

WED = date(2026, 10, 14)  # a Wednesday


@pytest.mark.parametrize("text,expected,approx", [
    ("besok", date(2026, 10, 15), False),
    ("lusa", date(2026, 10, 16), False),
    ("hari ini", WED, False),
    ("Jumat", date(2026, 10, 16), True),
    ("Jumat ini", date(2026, 10, 16), False),
    ("Jumat depan", date(2026, 10, 23), False),
    ("Rabu", date(2026, 10, 21), True),  # same weekday means next week, not today
    ("minggu depan", date(2026, 10, 23), True),
    ("2 minggu lagi", date(2026, 10, 28), False),
    ("tiga hari lagi", date(2026, 10, 17), False),
    ("akhir bulan", date(2026, 10, 31), True),
    ("20 Oktober", date(2026, 10, 20), False),
    ("5 Oktober", date(2027, 10, 5), False),  # already past this year -> next occurrence
    ("20 Oktober 2026", date(2026, 10, 20), False),
    ("2026-11-01", date(2026, 11, 1), False),
    ("bulan depan", date(2026, 11, 30), True),
])
def test_resolves(text, expected, approx):
    r = resolve_deadline(text, WED)
    assert r is not None
    assert (r.date, r.approximate) == (expected, approx)


@pytest.mark.parametrize("text", [None, "", "nanti saja", "31 Februari", "2026-13-40"])
def test_unresolvable_returns_none(text):
    assert resolve_deadline(text, WED) is None
