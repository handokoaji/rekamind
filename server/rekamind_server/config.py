from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REKAMIND_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".rekamind")
    # Empty means "sqlite file inside data_dir"; set to a postgresql+asyncpg:// URL for a shared server.
    database_url: str = ""
    # Local mode runs the worker inside the API process; a dedicated GPU server
    # can set this to false and run `python -m rekamind_server.worker` instead.
    worker_inprocess: bool = True
    worker_poll_seconds: float = 1.0
    language: str = "id"
    # "fake" = deterministic stub engines for UI development. Real engines (cuda, vulkan,
    # openvino, remote) are added behind the same Engines contract; "none" refuses to process.
    engines: str = "none"

    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'rekamind.db'}"
