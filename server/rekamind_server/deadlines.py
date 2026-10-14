"""Deterministic resolution of Indonesian deadline phrases to calendar dates.

The LLM is asked only to copy the phrase it heard ("Jumat depan"); turning it
into a date is done here, against the meeting date, because LLMs do date
arithmetic unreliably and a wrong deadline is worse than an unresolved one.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_DAYS = {"senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "jum'at": 4, "sabtu": 5, "minggu": 6}
_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7,
    "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}
_UNIT_DAYS = {"hari": 1, "minggu": 7, "pekan": 7}
_NUMBER_WORDS = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7}


@dataclass(frozen=True)
class ResolvedDeadline:
    date: date
    # True when the phrase is inherently vague ("minggu depan"); the UI should
    # show it as a suggestion, not a commitment.
    approximate: bool = False


def _next_weekday(base: date, weekday: int, *, strictly_after: bool = True) -> date:
    delta = (weekday - base.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return base + timedelta(days=delta)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def resolve_deadline(text: str | None, meeting_date: date) -> ResolvedDeadline | None:
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.strip().lower())

    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return ResolvedDeadline(d) if d else None

    if t in {"hari ini", "sekarang", "today"}:
        return ResolvedDeadline(meeting_date)
    if t == "besok":
        return ResolvedDeadline(meeting_date + timedelta(days=1))
    if t == "lusa":
        return ResolvedDeadline(meeting_date + timedelta(days=2))

    if m := re.fullmatch(r"(\d+|" + "|".join(_NUMBER_WORDS) + r") (hari|minggu|pekan) (lagi|ke depan|dari sekarang)", t):
        n = int(m[1]) if m[1].isdigit() else _NUMBER_WORDS[m[1]]
        return ResolvedDeadline(meeting_date + timedelta(days=n * _UNIT_DAYS[m[2]]))

    if t in {"minggu depan", "pekan depan"}:
        # Ambiguous on purpose: Monday-of-next-week vs end-of-next-week.
        # End of the working week is the safer reading for a deadline.
        monday = meeting_date + timedelta(days=7 - meeting_date.weekday())
        return ResolvedDeadline(monday + timedelta(days=4), approximate=True)
    if t in {"akhir minggu", "akhir pekan ini", "minggu ini", "pekan ini"}:
        return ResolvedDeadline(meeting_date + timedelta(days=4 - meeting_date.weekday())
                                if meeting_date.weekday() <= 4 else meeting_date, approximate=True)
    if t in {"akhir bulan", "akhir bulan ini"}:
        return ResolvedDeadline(
            date(meeting_date.year, meeting_date.month, calendar.monthrange(meeting_date.year, meeting_date.month)[1]),
            approximate=True,
        )
    if t == "bulan depan":
        y, mo = (meeting_date.year + (meeting_date.month == 12), meeting_date.month % 12 + 1)
        return ResolvedDeadline(date(y, mo, calendar.monthrange(y, mo)[1]), approximate=True)

    # "jumat" / "jumat ini" -> next such weekday; "jumat depan" -> that weekday in next week.
    if m := re.fullmatch(r"(?:hari )?(" + "|".join(re.escape(d) for d in _DAYS) + r")(?: (ini|depan))?", t):
        wd = _DAYS[m[1]]
        if m[2] == "depan":
            monday_next = meeting_date + timedelta(days=7 - meeting_date.weekday())
            return ResolvedDeadline(monday_next + timedelta(days=wd))
        return ResolvedDeadline(_next_weekday(meeting_date, wd), approximate=m[2] is None)

    # "20 oktober" / "20 oktober 2026" -> explicit; without a year, the next occurrence.
    if m := re.fullmatch(r"(\d{1,2}) (" + "|".join(_MONTHS) + r")(?: (\d{4}))?", t):
        day, month = int(m[1]), _MONTHS[m[2]]
        if m[3]:
            d = _safe_date(int(m[3]), month, day)
        else:
            d = _safe_date(meeting_date.year, month, day)
            if d and d < meeting_date:
                d = _safe_date(meeting_date.year + 1, month, day)
        return ResolvedDeadline(d) if d else None

    return None  # unknown phrase: keep the raw text, leave the date empty
