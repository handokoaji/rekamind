import os
from pathlib import Path

from app.config import get_settings


def test_settings_loads_from_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_USER=u\n"
        "POSTGRES_PASSWORD=p\n"
        "POSTGRES_DB=d\n"
        "DATABASE_URL=postgresql+asyncpg://u:p@localhost:5432/d\n"
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.recordings_dir == Path("./recordings")
    assert settings.groq_api_key == ""
