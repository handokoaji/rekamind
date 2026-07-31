import json
from pathlib import Path

from app import settings_store


def test_config_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert settings_store.config_dir() == tmp_path / "MeetingRecorder"


def test_config_path_is_config_json_inside_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert settings_store.config_path() == tmp_path / "MeetingRecorder" / "config.json"


def test_load_packaged_config_returns_none_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert settings_store.load_packaged_config() is None


def test_save_then_load_packaged_config_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = {"storage_backend": "sqlite", "groq_api_key": "gk", "hf_token": "hf"}

    settings_store.save_packaged_config(data)

    assert settings_store.load_packaged_config() == data


def test_save_packaged_config_creates_config_dir_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert not (tmp_path / "MeetingRecorder").exists()

    settings_store.save_packaged_config({"storage_backend": "sqlite"})

    assert settings_store.config_path().exists()


def test_sqlite_db_path_is_inside_config_dir_and_creates_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = settings_store.sqlite_db_path()
    assert path == tmp_path / "MeetingRecorder" / "meeting.db"
    assert path.parent.exists()  # eagerly created so sqlite can open the file


def test_recordings_dir_path_is_inside_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert settings_store.recordings_dir_path() == tmp_path / "MeetingRecorder" / "recordings"


def test_is_dev_mode_true_when_dot_env_exists_in_cwd(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("X=1")
    monkeypatch.chdir(tmp_path)
    assert settings_store.is_dev_mode() is True


def test_is_dev_mode_false_when_no_dot_env_in_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert settings_store.is_dev_mode() is False
