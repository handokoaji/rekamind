from datetime import datetime, timezone
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


def to_wib(value: datetime) -> datetime:
    """Timestamps are always STORED in UTC; WIB is a display-only concern
    ("tetap simpan UTC, tampilkan WIB di UI & docx"). A naive datetime is
    treated as UTC because every writer in this app produces UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WIB)
