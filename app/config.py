import re
import socket
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.settings_store import (
    is_dev_mode, load_packaged_config, recordings_dir_path, sqlite_db_path,
)

# Mirrors app/sync/minio_client.py's _SAFE_PATH_COMPONENT charset -- device_id
# ends up in MinIO object paths, so a raw hostname (which can contain spaces,
# dots, etc.) needs sanitizing before use.
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    storage_backend: Literal["sqlite", "postgres"] = "sqlite"

    # Only required when storage_backend == "postgres" -- validated at
    # database_url build time, not at Settings-construction time, so a
    # sqlite-backend instance never needs to fill these in.
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None

    groq_api_key: str = ""
    hf_token: str = ""
    device_id: str = ""
    device_label: str = ""
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = ""
    recordings_dir: Path = Path("./recordings")
    asr_backend_override: str = ""
    # Independent from asr_backend_override: lets the live-preview pipeline
    # use a different backend than the batch pass. Empty means "same as
    # batch", i.e. today's behavior, unchanged.
    live_asr_backend_override: str = ""

    @model_validator(mode="after")
    def _default_device_identity(self) -> "Settings":
        # No config UI has to be filled in for this to work: an unset
        # device_id/device_label falls back to this machine's hostname
        # instead of staying blank (which used to show up as "Tidak
        # diketahui" everywhere and made every blank-config install collide
        # under the same identity during sync).
        if not self.device_label:
            self.device_label = socket.gethostname()
        if not self.device_id:
            self.device_id = _UNSAFE_ID_CHARS.sub("-", socket.gethostname())
        return self

    @property
    def database_url(self) -> str:
        if self.storage_backend == "sqlite":
            return f"sqlite+aiosqlite:///{sqlite_db_path().as_posix()}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def minio_is_configured(self) -> bool:
        return bool(
            self.minio_endpoint and self.minio_access_key
            and self.minio_secret_key and self.minio_bucket
        )


@lru_cache
def get_settings() -> Settings:
    if is_dev_mode():
        return Settings()
    data = load_packaged_config() or {}
    data.setdefault("recordings_dir", str(recordings_dir_path()))
    return Settings(**data)
