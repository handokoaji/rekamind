from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.settings_store import (
    is_dev_mode, load_packaged_config, recordings_dir_path, sqlite_db_path,
)


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
    recordings_dir: Path = Path("./recordings")
    asr_backend_override: str = ""

    @property
    def database_url(self) -> str:
        if self.storage_backend == "sqlite":
            return f"sqlite+aiosqlite:///{sqlite_db_path().as_posix()}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    if is_dev_mode():
        return Settings()
    data = load_packaged_config() or {}
    data.setdefault("recordings_dir", str(recordings_dir_path()))
    return Settings(**data)
