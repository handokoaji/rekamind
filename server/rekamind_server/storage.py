import asyncio
import logging
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Protocol

log = logging.getLogger(__name__)

Source = Literal["mic", "speaker"]
_MEETING_ID = re.compile(r"[0-9a-f]{32}")


def _check(meeting_id: str, source: str) -> None:
    # meeting_id comes from a URL; never let it steer a filesystem path or an object key.
    if not _MEETING_ID.fullmatch(meeting_id) or source not in ("mic", "speaker"):
        raise ValueError("invalid meeting id or source")


class Storage(Protocol):
    async def save_audio(self, meeting_id: str, source: Source, chunks: AsyncIterator[bytes]) -> int: ...

    async def audio_path(self, meeting_id: str, source: Source) -> Path | None:
        """A local file the ASR engine can read; downloaded first when the audio lives remotely."""
        ...

    def release_local(self, meeting_id: str) -> None:
        """Drop any local copy that exists only as a cache of remote storage."""
        ...


async def _spool(chunks: AsyncIterator[bytes], dest: Path) -> int:
    """Write an upload to disk chunk by chunk: memory stays flat however long the meeting was."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as f:
        async for chunk in chunks:
            f.write(chunk)
            size += len(chunk)
    return size


class LocalStorage:
    def __init__(self, root: Path):
        self._root = root

    def _path(self, meeting_id: str, source: Source) -> Path:
        _check(meeting_id, source)
        return self._root / "recordings" / meeting_id / f"{source}.wav"

    async def save_audio(self, meeting_id: str, source: Source, chunks: AsyncIterator[bytes]) -> int:
        path = self._path(meeting_id, source)
        tmp = path.with_suffix(".part")
        size = await _spool(chunks, tmp)
        tmp.replace(path)  # a half-uploaded file never looks like a finished one
        return size

    async def audio_path(self, meeting_id: str, source: Source) -> Path | None:
        p = self._path(meeting_id, source)
        return p if p.is_file() else None

    def release_local(self, meeting_id: str) -> None:  # the files ARE the storage
        pass


class S3Storage:
    """Any S3-protocol store (MinIO, SeaweedFS, AWS...). Only the plain object API is used --
    no vendor admin calls -- so moving between them is a settings change.

    Audio is spooled to a local cache dir because the ASR engines need a real file; the cache
    is dropped by `release_local` once a job finishes, so a laptop does not accumulate copies."""

    def __init__(self, *, endpoint_url: str, bucket: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", prefix: str = "", cache_dir: Path, path_style: bool = True):
        import boto3
        from botocore.config import Config

        self._bucket = bucket
        self._prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._cache = cache_dir
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint_url or None, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(s3={"addressing_style": "path" if path_style else "auto"},
                          retries={"max_attempts": 5, "mode": "standard"}),
        )

    def _key(self, meeting_id: str, source: Source) -> str:
        _check(meeting_id, source)
        return f"{self._prefix}recordings/{meeting_id}/{source}.wav"

    def _local(self, meeting_id: str, source: Source) -> Path:
        _check(meeting_id, source)
        return self._cache / meeting_id / f"{source}.wav"

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
                raise
            self._s3.create_bucket(Bucket=self._bucket)
            log.info("created bucket %s", self._bucket)

    async def save_audio(self, meeting_id: str, source: Source, chunks: AsyncIterator[bytes]) -> int:
        local = self._local(meeting_id, source)
        tmp = local.with_suffix(".part")
        size = await _spool(chunks, tmp)
        if size == 0:
            tmp.unlink(missing_ok=True)
            return 0
        tmp.replace(local)
        # upload_file switches to multipart on its own for large recordings.
        await asyncio.to_thread(self._s3.upload_file, str(local), self._bucket, self._key(meeting_id, source))
        return size

    async def audio_path(self, meeting_id: str, source: Source) -> Path | None:
        from botocore.exceptions import ClientError

        local = self._local(meeting_id, source)
        if local.is_file():
            return local
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(".part")
        try:
            await asyncio.to_thread(self._s3.download_file, self._bucket, self._key(meeting_id, source), str(tmp))
        except ClientError as exc:
            tmp.unlink(missing_ok=True)
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        tmp.replace(local)
        return local

    def release_local(self, meeting_id: str) -> None:
        _check(meeting_id, "mic")
        shutil.rmtree(self._cache / meeting_id, ignore_errors=True)
