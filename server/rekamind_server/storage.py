import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Protocol

Source = Literal["mic", "speaker"]
_MEETING_ID = re.compile(r"[0-9a-f]{32}")


class Storage(Protocol):
    async def save_audio(self, meeting_id: str, source: Source, chunks: AsyncIterator[bytes]) -> int: ...
    def audio_path(self, meeting_id: str, source: Source) -> Path | None: ...


class LocalStorage:
    """Audio on local disk. An S3-protocol implementation (MinIO/SeaweedFS) will
    satisfy the same Protocol; callers never build paths themselves."""

    def __init__(self, root: Path):
        self._root = root

    def _path(self, meeting_id: str, source: Source) -> Path:
        # meeting_id comes from a URL; never let it steer the filesystem path.
        if not _MEETING_ID.fullmatch(meeting_id) or source not in ("mic", "speaker"):
            raise ValueError("invalid meeting id or source")
        return self._root / "recordings" / meeting_id / f"{source}.wav"

    async def save_audio(self, meeting_id: str, source: Source, chunks: AsyncIterator[bytes]) -> int:
        path = self._path(meeting_id, source)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        size = 0
        with tmp.open("wb") as f:
            async for chunk in chunks:
                f.write(chunk)
                size += len(chunk)
        tmp.replace(path)  # a half-uploaded file never looks like a finished one
        return size

    def audio_path(self, meeting_id: str, source: Source) -> Path | None:
        p = self._path(meeting_id, source)
        return p if p.is_file() else None
