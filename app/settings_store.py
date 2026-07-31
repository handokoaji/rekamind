import json
import os
import uuid
from pathlib import Path

_APP_DIR_NAME = "MeetingRecorder"


def config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / _APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def sqlite_db_path() -> Path:
    config_dir().mkdir(parents=True, exist_ok=True)
    return config_dir() / "meeting.db"


def recordings_dir_path() -> Path:
    return config_dir() / "recordings"


def load_packaged_config() -> dict | None:
    path = config_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_packaged_config(data: dict) -> None:
    # Copy rather than mutate: callers (e.g. the wizard's submitted dict)
    # must not see a device_id silently appear in their own dict after this
    # call returns.
    to_save = dict(data)
    if not to_save.get("device_id"):
        existing = load_packaged_config() or {}
        to_save["device_id"] = existing.get("device_id") or uuid.uuid4().hex
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(to_save, indent=2), encoding="utf-8")


def is_dev_mode() -> bool:
    return Path(".env").exists()
