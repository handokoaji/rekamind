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


def format_offset(ms: int) -> str:
    """Offset from the start of the recording, e.g. 01:02:03."""
    seconds = ms // 1000
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def format_transcript_lines(rows) -> list[str]:
    """rows from repo.get_final_transcript_timed -> `[start - end] Speaker: text`."""
    return [
        f"[{format_offset(start)} - {format_offset(end)}] {label}: {text}"
        for start, end, label, text in rows
    ]
