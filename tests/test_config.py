# tests/test_config.py
from pathlib import Path

from app.config import get_settings


def test_settings_loads_postgres_from_env_in_dev_mode(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "STORAGE_BACKEND=postgres\n"
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_USER=u\n"
        "POSTGRES_PASSWORD=p\n"
        "POSTGRES_DB=d\n"
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.storage_backend == "postgres"
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.recordings_dir == Path("./recordings")
    assert settings.groq_api_key == ""
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost:5432/d"


def test_settings_defaults_to_sqlite_when_storage_backend_unset(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=g\n")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.storage_backend == "sqlite"
    assert settings.postgres_host is None
    assert settings.database_url.startswith("sqlite+aiosqlite:///")


def test_database_url_sqlite_points_at_sqlite_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no .env here -> packaged mode
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.storage_backend == "sqlite"
    expected = (tmp_path / "MeetingRecorder" / "meeting.db").as_posix()
    assert settings.database_url == f"sqlite+aiosqlite:///{expected}"


def test_packaged_mode_reads_config_json_and_defaults_recordings_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no .env -> packaged mode
    from app import settings_store
    settings_store.save_packaged_config({
        "storage_backend": "postgres",
        "postgres_host": "db.internal", "postgres_port": 5432,
        "postgres_user": "u", "postgres_password": "p", "postgres_db": "d",
        "groq_api_key": "gk", "hf_token": "hf",
    })
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.storage_backend == "postgres"
    assert settings.groq_api_key == "gk"
    assert settings.recordings_dir == tmp_path / "MeetingRecorder" / "recordings"
