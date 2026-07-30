from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    database_url: str
    groq_api_key: str = ""
    hf_token: str = ""
    recordings_dir: Path = Path("./recordings")
    asr_backend_override: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
