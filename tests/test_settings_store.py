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
    loaded = settings_store.load_packaged_config()

    # save_packaged_config also stamps a generated device_id (tested below) --
    # everything else must round-trip exactly.
    assert loaded["device_id"]
    del loaded["device_id"]
    assert loaded == data


def test_save_packaged_config_generates_device_id_on_first_save(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    settings_store.save_packaged_config({"storage_backend": "sqlite"})

    saved = settings_store.load_packaged_config()
    assert saved["device_id"]  # non-empty, generated
    assert len(saved["device_id"]) == 32  # uuid4().hex length


def test_save_packaged_config_preserves_device_id_across_resaves(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings_store.save_packaged_config({"storage_backend": "sqlite"})
    first_id = settings_store.load_packaged_config()["device_id"]

    settings_store.save_packaged_config({"storage_backend": "postgres", "device_label": "Laptop Budi"})

    assert settings_store.load_packaged_config()["device_id"] == first_id


def test_save_packaged_config_keeps_caller_supplied_device_id(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    settings_store.save_packaged_config({"storage_backend": "sqlite", "device_id": "explicit123"})

    assert settings_store.load_packaged_config()["device_id"] == "explicit123"


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
