"""The time zone meetings are read in. Default WIB (Asia/Jakarta); set REKAMIND_TIMEZONE for WITA/WIT/other.

Timestamps are stored in UTC. Anything that turns one into a *calendar date or a clock time a person reads*
must go through here: "besok" said at 01:00 WIB is a different date than the UTC date of that moment.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT = "Asia/Jakarta"


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"REKAMIND_TIMEZONE='{name}' bukan zona waktu yang dikenal (contoh: Asia/Jakarta, Asia/Makassar, Asia/Jayapura, UTC)") from exc


def to_zone(dt: datetime, tz: ZoneInfo) -> datetime:
    """SQLite hands timestamps back without a zone; they were stored as UTC."""
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone(tz)


def label(tz: ZoneInfo, at: datetime | None = None) -> str:
    """'WIB' / 'WITA' / 'WIT' where tzdata knows them, else the offset ('+09:00')."""
    when = at or datetime.now(UTC)
    name = when.astimezone(tz).tzname() or ""
    return name if name.isalpha() else when.astimezone(tz).strftime("%z")[:3] + ":" + when.astimezone(tz).strftime("%z")[3:]
