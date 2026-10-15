# Storage Backend Abstraction & First-Run Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SQLite as a zero-config default storage backend (Postgres stays available as an advanced option), and a first-run Tk wizard (plus a "Pengaturan" reopen path) that collects it and optional Groq/HF API keys, so the app can be distributed as a standalone install without every user needing their own Postgres server or hand-edited `.env`.

**Architecture:** A new `app/settings_store.py` owns the packaged-install config file (`%LOCALAPPDATA%\MeetingRecorder\config.json`) and dev/packaged mode detection. `app/config.py::Settings` gains a `storage_backend` field and computes `database_url` instead of storing it redundantly. `app/ui/setup_wizard.py` is a small Tk window reused both for first-run (its own root) and "Pengaturan" (a `Toplevel` on the existing root).

**Tech Stack:** Python 3.11+, pydantic-settings, Tkinter, SQLAlchemy async (existing), pytest.

## Global Constraints

- Dev mode (a `.env` file present) must behave EXACTLY as it does today — this is the single most important constraint in the spec. Verify by running the full existing test suite after every task.
- No new third-party dependencies (json/pathlib/os/tkinter are all stdlib).
- Postgres fields become optional at the type level; nothing may require them unless `storage_backend == "postgres"`.
- All new Tk UI tests must follow the existing `_tk_available()` / `@pytest.mark.skipif` pattern used throughout `tests/ui/`.

---

### Task 1: `app/settings_store.py` — packaged config file I/O

**Files:**
- Create: `app/settings_store.py`
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Produces: `config_dir() -> Path`, `config_path() -> Path`, `sqlite_db_path() -> Path`, `recordings_dir_path() -> Path`, `load_packaged_config() -> dict | None`, `save_packaged_config(data: dict) -> None`, `is_dev_mode() -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings_store.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.settings_store'`

- [ ] **Step 3: Write the implementation**

```python
# app/settings_store.py
import json
import os
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
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_dev_mode() -> bool:
    return Path(".env").exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings_store.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/settings_store.py tests/test_settings_store.py
git commit -m "feat(settings): add packaged-install config store"
```

---

### Task 2: `app/config.py` — `storage_backend`, computed `database_url`, dev/packaged branching

**Files:**
- Modify: `app/config.py` (full rewrite of `Settings` + `get_settings`)
- Modify: `tests/test_config.py`
- Modify: `.env.example` (drop `DATABASE_URL`, keep `POSTGRES_*`, note the new var)
- Modify: `.env` (local, gitignored — add `STORAGE_BACKEND=postgres` so dev mode keeps using Postgres; see Step 6)

**Interfaces:**
- Consumes: `app.settings_store.{is_dev_mode, load_packaged_config, sqlite_db_path, recordings_dir_path}` (Task 1)
- Produces: `Settings.storage_backend: Literal["sqlite", "postgres"]`, `Settings.database_url` (property, was a field), `get_settings() -> Settings` (now branches on dev/packaged mode)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `test_settings_loads_postgres_from_env_in_dev_mode` and
`test_settings_defaults_to_sqlite_when_storage_backend_unset` fail because
`storage_backend`/computed `database_url` don't exist yet; the packaged-mode
tests fail because `get_settings()` doesn't branch on `is_dev_mode()` yet.

- [ ] **Step 3: Write the implementation**

```python
# app/config.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings_store.py tests/test_config.py -v`
Expected: all passed

- [ ] **Step 5: Update `.env.example`**

Replace the contents of `.env.example`:

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=your_postgres_user
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_DB=meeting_recorder
STORAGE_BACKEND=postgres

# Isi manual setelah dapat API key dari console.groq.com
GROQ_API_KEY=

# Isi manual: buat token read-only di huggingface.co/settings/tokens
# setelah accept terms di huggingface.co/pyannote/speaker-diarization-3.1
# dan huggingface.co/pyannote/segmentation-3.0
HF_TOKEN=
```

(`DATABASE_URL` is removed — it's computed from the fields above now.)

- [ ] **Step 6: Preserve local dev behavior in the real `.env`**

The real (gitignored) `.env` in this repo has no `STORAGE_BACKEND` key. Under
the new default (`"sqlite"`), dev mode would silently switch away from
Postgres — a direct violation of the spec's "dev mode must not change"
requirement. Add the missing line so this repo's own dev workflow keeps
using Postgres exactly as before:

```bash
echo "STORAGE_BACKEND=postgres" >> .env
```

Verify: `grep STORAGE_BACKEND .env` shows `STORAGE_BACKEND=postgres`.

- [ ] **Step 7: Run the full existing test suite (regression check)**

Run: `pytest -q`
Expected: same pass count as before this task (no new failures) — this is
the constraint check for "dev mode unchanged."

- [ ] **Step 8: Commit**

```bash
git add app/config.py tests/test_config.py .env.example
git commit -m "feat(config): add storage_backend, compute database_url, branch on dev/packaged mode"
```

(`.env` is gitignored and must NOT be committed.)

---

### Task 3: `app/ui/setup_wizard.py` — wizard fields and show/hide behavior

**Files:**
- Create: `app/ui/setup_wizard.py`
- Test: `tests/ui/test_setup_wizard.py`

**Interfaces:**
- Consumes: nothing from earlier tasks yet (this task is pure UI structure)
- Produces: `SetupWizard(parent: tk.Misc | None = None, initial: dict | None = None)` with attributes `.window`, `.storage_var`, `.postgres_host_var`, `.postgres_port_var`, `.postgres_user_var`, `.postgres_password_var`, `.postgres_db_var`, `.groq_var`, `.hf_var`, `.error_var`, and methods `._update_postgres_visibility()`, `.run() -> dict | None` (`.run()` is stubbed to return `None` in this task — real submit logic is Task 4)

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_setup_wizard.py
import tkinter as tk

import pytest

from app.ui.setup_wizard import SetupWizard


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_defaults_to_sqlite_and_hides_postgres_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root)

    assert wizard.storage_var.get() == "sqlite"
    assert str(wizard._postgres_frame.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_postgres_shows_postgres_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root)

    wizard.storage_var.set("postgres")
    wizard._update_postgres_visibility()

    assert str(wizard._postgres_frame.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_initial_values_prefill_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root, initial={
        "storage_backend": "postgres", "postgres_host": "db.internal",
        "postgres_port": 5432, "groq_api_key": "gk", "hf_token": "hf",
    })

    assert wizard.storage_var.get() == "postgres"
    assert wizard.postgres_host_var.get() == "db.internal"
    assert wizard.postgres_port_var.get() == "5432"
    assert wizard.groq_var.get() == "gk"
    assert wizard.hf_var.get() == "hf"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_lewati_buttons_clear_their_field():
    root = tk.Tk()
    wizard = SetupWizard(parent=root, initial={"groq_api_key": "gk", "hf_token": "hf"})

    wizard._groq_skip_button.invoke()
    wizard._hf_skip_button.invoke()

    assert wizard.groq_var.get() == ""
    assert wizard.hf_var.get() == ""
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui.setup_wizard'`

- [ ] **Step 3: Write the implementation**

```python
# app/ui/setup_wizard.py
import tkinter as tk


class SetupWizard:
    """Modal storage/API-key config window.

    parent=None: no Tk root exists yet (first-run, called before MainWindow)
    -- this becomes the root itself and .run() drives its own mainloop.
    parent=<existing Tk root>: reopened from a running app ("Pengaturan")
    -- becomes a Toplevel, .run() blocks via wait_window() instead.
    """

    def __init__(self, parent: tk.Misc | None = None, initial: dict | None = None):
        initial = initial or {}
        self._result: dict | None = None
        self._is_root = parent is None
        self.window = tk.Tk() if self._is_root else tk.Toplevel(parent)
        self.window.title("Pengaturan Meeting Recorder")

        tk.Label(self.window, text="Penyimpanan:").pack(anchor="w")
        self.storage_var = tk.StringVar(value=initial.get("storage_backend", "sqlite"))
        tk.Radiobutton(
            self.window, text="SQLite (default)", variable=self.storage_var,
            value="sqlite", command=self._update_postgres_visibility,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.window, text="Postgres (lanjutan)", variable=self.storage_var,
            value="postgres", command=self._update_postgres_visibility,
        ).pack(anchor="w")

        self._postgres_frame = tk.Frame(self.window)
        self.postgres_host_var = tk.StringVar(value=initial.get("postgres_host") or "")
        self.postgres_port_var = tk.StringVar(value=str(initial.get("postgres_port") or ""))
        self.postgres_user_var = tk.StringVar(value=initial.get("postgres_user") or "")
        self.postgres_password_var = tk.StringVar(value=initial.get("postgres_password") or "")
        self.postgres_db_var = tk.StringVar(value=initial.get("postgres_db") or "")
        for label, var in [
            ("Host", self.postgres_host_var), ("Port", self.postgres_port_var),
            ("User", self.postgres_user_var), ("Password", self.postgres_password_var),
            ("Database", self.postgres_db_var),
        ]:
            row = tk.Frame(self._postgres_frame)
            row.pack(fill="x")
            tk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)

        tk.Label(self.window, text="GROQ_API_KEY (opsional):").pack(anchor="w")
        groq_row = tk.Frame(self.window)
        groq_row.pack(fill="x")
        self.groq_var = tk.StringVar(value=initial.get("groq_api_key", ""))
        tk.Entry(groq_row, textvariable=self.groq_var).pack(side="left", fill="x", expand=True)
        self._groq_skip_button = tk.Button(
            groq_row, text="Lewati", command=lambda: self.groq_var.set("")
        )
        self._groq_skip_button.pack(side="left")

        tk.Label(self.window, text="HF_TOKEN (opsional):").pack(anchor="w")
        hf_row = tk.Frame(self.window)
        hf_row.pack(fill="x")
        self.hf_var = tk.StringVar(value=initial.get("hf_token", ""))
        tk.Entry(hf_row, textvariable=self.hf_var).pack(side="left", fill="x", expand=True)
        self._hf_skip_button = tk.Button(
            hf_row, text="Lewati", command=lambda: self.hf_var.set("")
        )
        self._hf_skip_button.pack(side="left")

        self.error_var = tk.StringVar()
        tk.Label(self.window, textvariable=self.error_var, fg="red").pack(anchor="w")

        self._submit_button = tk.Button(self.window, text="Simpan & Mulai", command=self._on_submit)
        self._submit_button.pack()

        self._update_postgres_visibility()

    def _update_postgres_visibility(self) -> None:
        if self.storage_var.get() == "postgres":
            self._postgres_frame.pack(fill="x")
        else:
            self._postgres_frame.pack_forget()

    def _on_submit(self) -> None:
        self.window.destroy()  # replaced with real validation/save in Task 4

    def run(self) -> dict | None:
        if self._is_root:
            self.window.mainloop()
        else:
            self.window.grab_set()
            self.window.wait_window()
        return self._result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/ui/setup_wizard.py tests/ui/test_setup_wizard.py
git commit -m "feat(ui): add setup wizard fields (storage choice, postgres show/hide, API keys)"
```

---

### Task 4: Wizard submit — validation, Postgres connectivity check, save

**Files:**
- Modify: `app/ui/setup_wizard.py` (`_on_submit`)
- Modify: `tests/ui/test_setup_wizard.py` (append)

**Interfaces:**
- Consumes: `app.storage.db.make_engine(url: str) -> AsyncEngine` (existing), `app.settings_store.save_packaged_config(data: dict) -> None` (Task 1)
- Produces: `SetupWizard._on_submit()` now validates + saves; `SetupWizard.run()` returns the saved dict on success

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_setup_wizard.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import app.ui.setup_wizard as setup_wizard_module


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_sqlite_saves_config_without_connection_check(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)
    make_engine_calls = []
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: make_engine_calls.append(url))

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.groq_var.set("gk")
    wizard.hf_var.set("hf")

    wizard._submit_button.invoke()

    assert make_engine_calls == []  # sqlite never needs a connectivity check
    assert saved == {"storage_backend": "sqlite", "groq_api_key": "gk", "hf_token": "hf"}
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_postgres_success_saves_config(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)

    fake_conn_cm = MagicMock()
    fake_conn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_conn_cm.__aexit__ = AsyncMock(return_value=False)
    fake_engine = MagicMock()
    fake_engine.connect = MagicMock(return_value=fake_conn_cm)
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: fake_engine)

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.storage_var.set("postgres")
    wizard.postgres_host_var.set("db.internal")
    wizard.postgres_port_var.set("5432")
    wizard.postgres_user_var.set("u")
    wizard.postgres_password_var.set("p")
    wizard.postgres_db_var.set("d")

    wizard._submit_button.invoke()

    assert saved["storage_backend"] == "postgres"
    assert saved["postgres_host"] == "db.internal"
    assert saved["postgres_port"] == 5432
    assert wizard.error_var.get() == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_postgres_connection_failure_shows_error_and_keeps_window_open(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)

    fake_engine = MagicMock()
    fake_engine.connect = MagicMock(side_effect=OSError("connection refused"))
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: fake_engine)

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.storage_var.set("postgres")
    wizard.postgres_host_var.set("db.internal")
    wizard.postgres_port_var.set("5432")
    wizard.postgres_user_var.set("u")
    wizard.postgres_password_var.set("p")
    wizard.postgres_db_var.set("d")

    wizard._submit_button.invoke()

    assert saved == {}
    assert "connection refused" in wizard.error_var.get()
    assert wizard.window.winfo_exists()  # window must stay open, not destroyed
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: the 3 new tests FAIL (submit currently just destroys the window
without saving anything or checking connectivity)

- [ ] **Step 3: Write the implementation**

Replace `_on_submit` in `app/ui/setup_wizard.py`, and add the needed imports
at the top of the file:

```python
# add to imports at the top of app/ui/setup_wizard.py
import asyncio

from app.settings_store import save_packaged_config
from app.storage.db import make_engine
```

```python
# replace _on_submit in app/ui/setup_wizard.py
def _check_postgres_connection(self, url: str) -> str | None:
    """Returns an error message, or None if the connection succeeded."""
    async def _try() -> None:
        engine = make_engine(url)
        try:
            async with asyncio.timeout(5):
                async with engine.connect():
                    pass
        finally:
            await engine.dispose()

    try:
        asyncio.run(_try())
        return None
    except Exception as exc:
        return str(exc)

def _on_submit(self) -> None:
    data = {
        "storage_backend": self.storage_var.get(),
        "groq_api_key": self.groq_var.get(),
        "hf_token": self.hf_var.get(),
    }
    if self.storage_var.get() == "postgres":
        data["postgres_host"] = self.postgres_host_var.get()
        data["postgres_port"] = int(self.postgres_port_var.get() or 0)
        data["postgres_user"] = self.postgres_user_var.get()
        data["postgres_password"] = self.postgres_password_var.get()
        data["postgres_db"] = self.postgres_db_var.get()
        url = (
            f"postgresql+asyncpg://{data['postgres_user']}:{data['postgres_password']}"
            f"@{data['postgres_host']}:{data['postgres_port']}/{data['postgres_db']}"
        )
        error = self._check_postgres_connection(url)
        if error:
            self.error_var.set(f"Tidak bisa konek ke Postgres: {error}")
            return
    save_packaged_config(data)
    self._result = data
    self.window.destroy()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/ui/setup_wizard.py tests/ui/test_setup_wizard.py
git commit -m "feat(ui): validate and save setup wizard submission"
```

---

### Task 5: Wire the first-run wizard into `app/main.py`

**Files:**
- Modify: `app/main.py` (`main()`)
- Modify: `tests/test_main.py` (append)

**Interfaces:**
- Consumes: `app.settings_store.{is_dev_mode, load_packaged_config}` (Task 1), `app.ui.setup_wizard.SetupWizard` (Task 3/4), `app.config.get_settings` (Task 2, now cache-clearable)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_main_shows_wizard_on_first_run_and_reports_cancellation(monkeypatch):
    """Packaged mode, no config.json yet: the wizard must run, and if the
    user closes it without submitting, the gate reports False so main()
    knows not to proceed to creating MainWindow."""
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main, "load_packaged_config", lambda: None)

    wizard_calls = []

    class FakeWizard:
        def __init__(self, parent=None, initial=None):
            wizard_calls.append((parent, initial))

        def run(self):
            return None  # user closed without submitting

    monkeypatch.setattr(main, "SetupWizard", FakeWizard)

    proceed = main.run_first_run_wizard_if_needed()

    assert wizard_calls == [(None, None)]
    assert proceed is False


def test_main_skips_wizard_when_config_already_exists(monkeypatch):
    monkeypatch.setattr(main, "is_dev_mode", lambda: False)
    monkeypatch.setattr(main, "load_packaged_config", lambda: {"storage_backend": "sqlite"})
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    main.run_first_run_wizard_if_needed()

    assert wizard_calls == []


def test_main_skips_wizard_in_dev_mode(monkeypatch):
    monkeypatch.setattr(main, "is_dev_mode", lambda: True)
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    main.run_first_run_wizard_if_needed()

    assert wizard_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v -k wizard`
Expected: FAIL — `main.run_first_run_wizard_if_needed`, `main.is_dev_mode`,
`main.load_packaged_config`, `main.SetupWizard` don't exist yet.

- [ ] **Step 3: Write the implementation**

Add these imports near the top of `app/main.py` (alongside the existing
`from app.config import get_settings` line):

```python
from app.settings_store import is_dev_mode, load_packaged_config
from app.ui.setup_wizard import SetupWizard
```

Add this function above `def main() -> None:`:

```python
def run_first_run_wizard_if_needed() -> bool:
    """Returns False if the app must not proceed (packaged mode, no config
    yet, and the user closed the wizard without submitting)."""
    if is_dev_mode() or load_packaged_config() is not None:
        return True
    result = SetupWizard(parent=None).run()
    return result is not None
```

Modify the start of `main()` (the existing `def main() -> None:` body) to
call this gate first:

```python
def main() -> None:
    configure_logging()
    if not run_first_run_wizard_if_needed():
        return
    get_settings.cache_clear()
    settings = get_settings()
    ...  # rest of main() unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v -k wizard`
Expected: 3 passed

Run: `pytest -q`
Expected: same pass count as before plus the 3 new tests, no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat(main): show setup wizard before the window on first run"
```

---

### Task 6: Startup DB-connection failure → "Buka Pengaturan" prompt

**Files:**
- Modify: `app/main.py` (`main()`)
- Modify: `tests/test_main.py` (append)

**Interfaces:**
- Consumes: `tkinter.messagebox.askyesno` (stdlib), `SetupWizard` (Task 3/4), `app.settings_store.save_packaged_config` (Task 1)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_handle_startup_db_error_reopens_wizard_on_yes(monkeypatch):
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: True)
    saved = []
    monkeypatch.setattr(main, "save_packaged_config", saved.append)

    class FakeWizard:
        def __init__(self, parent=None):
            pass

        def run(self):
            return {"storage_backend": "sqlite"}

    monkeypatch.setattr(main, "SetupWizard", FakeWizard)

    retried = main._handle_startup_db_error(RuntimeError("connection refused"))

    assert retried is True
    assert saved == [{"storage_backend": "sqlite"}]


def test_handle_startup_db_error_returns_false_on_no(monkeypatch):
    monkeypatch.setattr(main.messagebox, "askyesno", lambda *a, **k: False)
    wizard_calls = []
    monkeypatch.setattr(main, "SetupWizard", lambda **kw: wizard_calls.append(kw))

    retried = main._handle_startup_db_error(RuntimeError("connection refused"))

    assert retried is False
    assert wizard_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v -k startup_db_error`
Expected: FAIL — `main._handle_startup_db_error` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Add this import near the top of `app/main.py`:

```python
import tkinter as tk
from tkinter import messagebox
```

(Check first — `tkinter as tk` is already imported in `app/main.py`; only
add `messagebox` if it isn't already there.)

Add this import alongside the Task 1 imports:

```python
from app.settings_store import save_packaged_config
```

Add this function above `def main() -> None:`:

```python
def _handle_startup_db_error(exc: Exception) -> bool:
    """Returns True if the user updated settings via the wizard and startup
    should retry; False if they declined and the app should just exit."""
    root = tk.Tk()
    root.withdraw()
    reopen = messagebox.askyesno(
        "Meeting Recorder - Error",
        f"Tidak bisa konek ke database: {exc}\n\nBuka Pengaturan sekarang?",
    )
    if not reopen:
        root.destroy()
        return False
    result = SetupWizard(parent=None).run()
    root.destroy()
    if result is None:
        return False
    save_packaged_config(result)
    return True
```

Wrap the existing `init_db` call in `main()` (currently
`asyncio.run(init_db(engine))` right after `engine = make_engine(settings.database_url)`)
with error handling:

```python
    engine = make_engine(settings.database_url)
    try:
        asyncio.run(init_db(engine))
    except Exception as exc:
        if not _handle_startup_db_error(exc):
            return
        get_settings.cache_clear()
        settings = get_settings()
        engine = make_engine(settings.database_url)
        asyncio.run(init_db(engine))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v -k startup_db_error`
Expected: 2 passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat(main): offer to reopen settings when startup DB connection fails"
```

---

### Task 7: "Pengaturan" button in `MainWindow`

**Files:**
- Modify: `app/ui/window.py`
- Modify: `tests/ui/test_window.py` (append)

**Interfaces:**
- Consumes: `SetupWizard` (Task 3/4), `app.config.get_settings` (Task 2), `app.settings_store.save_packaged_config` (Task 1)

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_window.py`:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_pengaturan_button_reopens_wizard_prefilled_and_saves_on_submit(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module

    class FakeSettings:
        storage_backend = "sqlite"
        postgres_host = None
        postgres_port = None
        postgres_user = None
        postgres_password = None
        postgres_db = None
        groq_api_key = "gk"
        hf_token = "hf"

    monkeypatch.setattr(window_module, "get_settings", lambda: FakeSettings())
    wizard_calls = []
    saved = []

    class FakeWizard:
        def __init__(self, parent=None, initial=None):
            wizard_calls.append((parent, initial))

        def run(self):
            return {"storage_backend": "sqlite", "groq_api_key": "gk2", "hf_token": "hf"}

    monkeypatch.setattr(window_module, "SetupWizard", FakeWizard)
    monkeypatch.setattr(window_module, "save_packaged_config", saved.append)
    monkeypatch.setattr(window_module.messagebox, "showinfo", lambda *a, **k: None)

    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_open_settings()

    assert wizard_calls == [(root, {
        "storage_backend": "sqlite", "postgres_host": None, "postgres_port": None,
        "postgres_user": None, "postgres_password": None, "postgres_db": None,
        "groq_api_key": "gk", "hf_token": "hf",
    })]
    assert saved == [{"storage_backend": "sqlite", "groq_api_key": "gk2", "hf_token": "hf"}]
    root.destroy()
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `pytest tests/ui/test_window.py -v -k pengaturan`
Expected: FAIL — no "Pengaturan" button/handler exists yet.

- [ ] **Step 3: Write the implementation**

Add these imports near the top of `app/ui/window.py`:

```python
from tkinter import messagebox

from app.config import get_settings
from app.settings_store import save_packaged_config
from app.ui.setup_wizard import SetupWizard
```

In `MainWindow.__init__`, next to the existing `nav` buttons
("Meeting Baru" / "Riwayat"), add:

```python
tk.Button(nav, text="Pengaturan", command=self._handle_open_settings).pack(side="left")
```

Add this method to `MainWindow`:

```python
def _handle_open_settings(self) -> None:
    settings = get_settings()
    initial = {
        "storage_backend": settings.storage_backend,
        "postgres_host": settings.postgres_host,
        "postgres_port": settings.postgres_port,
        "postgres_user": settings.postgres_user,
        "postgres_password": settings.postgres_password,
        "postgres_db": settings.postgres_db,
        "groq_api_key": settings.groq_api_key,
        "hf_token": settings.hf_token,
    }
    result = SetupWizard(parent=self._root, initial=initial).run()
    if result is not None:
        save_packaged_config(result)
        messagebox.showinfo("Pengaturan", "Restart aplikasi untuk menerapkan perubahan.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_window.py -v -k pengaturan`
Expected: 1 passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ui/window.py tests/ui/test_window.py
git commit -m "feat(ui): add Pengaturan button to reopen the setup wizard"
```

---

### Task 8: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass (same baseline count from before this plan, plus
every test added in Tasks 1-7); no `hardware`/`postgres`-marked tests ran
(excluded by default per `pytest.ini`, unchanged).

- [ ] **Step 2: Manually verify dev mode is untouched**

Run: `python -m app.main` from the existing dev checkout (with the real
`.env`, now containing `STORAGE_BACKEND=postgres` from Task 2 Step 6).
Expected: app starts exactly as before — no wizard appears (dev mode
short-circuits it), connects to the same Postgres server as always.

- [ ] **Step 3: Commit (if Step 2 required any fixes)**

```bash
git add -A
git commit -m "fix: address regressions found in full verification pass"
```

(Skip this commit entirely if Step 2 needed no changes.)
