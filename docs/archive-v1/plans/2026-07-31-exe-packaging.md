# Distributable .exe Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the app as a single Windows installer (PyInstaller + Inno Setup) that bundles ffmpeg but not AI models, plus a non-blocking startup update-availability notification.

**Architecture:** Application-code changes (ffmpeg PATH detection, update check, notification wiring) get the same TDD treatment as the rest of this series. The build pipeline itself (PyInstaller `.spec` file, Inno Setup `.iss` script) is procedural configuration with no pytest coverage — per the spec's own testing section, those tasks end in manual verification steps instead of a test run.

**Tech Stack:** PyInstaller, Inno Setup (external tools, not Python packages), stdlib `urllib.request`/`json`/`webbrowser` for the update check (no new HTTP client dependency — this is a single GET request, `urllib` covers it without adding `requests`/`httpx`).

## Global Constraints

- Independent of the other plans in this series, EXCEPT: it references `%LOCALAPPDATA%\MeetingRecorder\` as the config/data location, which must match whatever the storage-backend plan actually produced (`app/settings_store.py::config_dir()`) if that plan has landed — if not yet implemented, Task 4/5's Inno Setup notes about "never touches user data" still hold true by construction (the installer only ever writes to the install directory, never to `%LOCALAPPDATA%`).
- No new runtime HTTP client dependency for the update check — stdlib `urllib.request` only.
- The update check must be silent on any failure (offline, DNS failure, malformed response, timeout) — never an error dialog, never blocks startup.
- `RELEASES_API_URL`/`RELEASES_PAGE_URL` start empty (update check effectively disabled, zero network activity) until a maintainer fills them in once real releases exist — this is a deliberate manual step, not an oversight.

---

### Task 1: App version constant + bundled-ffmpeg PATH detection

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `app.__version__: str`; `main.py` prepends a bundled `ffmpeg/` directory (next to the running executable) to `PATH` before `check_ffmpeg_available()` runs

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_prepend_bundled_ffmpeg_adds_to_path_when_dir_exists(monkeypatch, tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "MeetingRecorder.exe"))
    monkeypatch.setenv("PATH", "C:\\existing")

    main.prepend_bundled_ffmpeg_to_path()

    assert str(ffmpeg_dir) in main.os.environ["PATH"]
    assert main.os.environ["PATH"].startswith(str(ffmpeg_dir))


def test_prepend_bundled_ffmpeg_no_op_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(main.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setenv("PATH", "C:\\existing")

    main.prepend_bundled_ffmpeg_to_path()

    assert main.os.environ["PATH"] == "C:\\existing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v -k bundled_ffmpeg`
Expected: FAIL — `main.prepend_bundled_ffmpeg_to_path` doesn't exist yet
(and `main.os` isn't imported yet either).

- [ ] **Step 3: Write the implementation**

Set `app/__init__.py`'s full contents:

```python
__version__ = "0.1.0"
```

(Must be kept in sync with `pyproject.toml`'s `version` field manually —
there are two independent version strings in this codebase now, one for
packaging metadata and one importable at runtime without needing to parse
TOML in a possibly-frozen executable.)

Add `import os` to the top of `app/main.py`, alongside the existing
`import sys`.

Add this function above `def main() -> None:`:

```python
def prepend_bundled_ffmpeg_to_path() -> None:
    bundled_ffmpeg_dir = Path(sys.executable).parent / "ffmpeg"
    if bundled_ffmpeg_dir.exists():
        os.environ["PATH"] = f"{bundled_ffmpeg_dir}{os.pathsep}{os.environ['PATH']}"
```

Call it at the very start of `main()`, before `check_ffmpeg_available()`:

```python
def main() -> None:
    configure_logging()
    prepend_bundled_ffmpeg_to_path()
    ...
```

(If the hardware-capability-check plan has already been implemented,
`main()` starts with `settings = get_settings()` then the
`detect_backend()` try/except before `check_ffmpeg_available()` — place
`prepend_bundled_ffmpeg_to_path()` as the first line either way, before
anything else.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v -k bundled_ffmpeg`
Expected: 2 passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/main.py tests/test_main.py
git commit -m "feat(main): add app version constant, detect bundled ffmpeg"
```

---

### Task 2: `app/update_check.py`

**Files:**
- Create: `app/update_check.py`
- Test: `tests/test_update_check.py`

**Interfaces:**
- Produces: `check_for_update(current_version: str, releases_api_url: str) -> str | None`, `RELEASES_API_URL: str`, `RELEASES_PAGE_URL: str` (both empty by default)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_update_check.py
import json
from unittest.mock import MagicMock

from app import update_check


def _fake_urlopen(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=response)


def test_returns_none_when_url_is_blank():
    assert update_check.check_for_update("0.1.0", "") is None


def test_detects_newer_version_github_shape(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.2.0"}))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") == "0.2.0"


def test_detects_newer_version_gitlab_shape(monkeypatch):
    """GitLab's releases endpoint returns a list, newest first."""
    monkeypatch.setattr(
        update_check.urllib.request, "urlopen",
        _fake_urlopen([{"tag_name": "v0.3.0"}, {"tag_name": "v0.2.0"}]),
    )
    assert update_check.check_for_update("0.1.0", "https://gitlab.example/releases") == "0.3.0"


def test_returns_none_when_already_latest(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.1.0"}))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None


def test_returns_none_when_current_is_newer_than_remote(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.1.0"}))
    assert update_check.check_for_update("0.2.0", "https://api.example/releases/latest") is None


def test_returns_none_on_network_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError("network unreachable")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _raise)
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None


def test_returns_none_on_malformed_response(monkeypatch):
    response = MagicMock()
    response.read.return_value = b"not json"
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(update_check.urllib.request, "urlopen", MagicMock(return_value=response))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_update_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.update_check'`

- [ ] **Step 3: Write the implementation**

```python
# app/update_check.py
import json
import urllib.request

# Filled in once when releases actually exist for this repo (GitHub or the
# UGM GitLab instance both expose a similar Releases API shape). Left blank
# on purpose: an empty URL means this feature makes zero network requests.
RELEASES_API_URL = ""
RELEASES_PAGE_URL = ""


def _parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.lstrip("v").split("."))


def _latest_tag(payload) -> str | None:
    if isinstance(payload, list):
        if not payload:
            return None
        return payload[0].get("tag_name")
    if isinstance(payload, dict):
        return payload.get("tag_name")
    return None


def check_for_update(current_version: str, releases_api_url: str) -> str | None:
    """Returns the newer version string (e.g. "0.2.0") if the Releases API
    reports one newer than current_version, else None -- including on any
    failure (blank URL, network error, malformed response). Never raises."""
    if not releases_api_url:
        return None
    try:
        with urllib.request.urlopen(releases_api_url, timeout=5) as response:
            payload = json.loads(response.read())
        tag = _latest_tag(payload)
        if not tag:
            return None
        latest = tag.lstrip("v")
        if _parse_version(latest) > _parse_version(current_version):
            return latest
        return None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_update_check.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/update_check.py tests/test_update_check.py
git commit -m "feat: add update-availability check against a Releases API"
```

---

### Task 3: Wire the update check into startup + a non-blocking notification

**Files:**
- Modify: `app/main.py`
- Modify: `app/ui/window.py`
- Test: `tests/test_main.py`
- Test: `tests/ui/test_window.py`

**Interfaces:**
- Consumes: `app.update_check.{check_for_update, RELEASES_API_URL, RELEASES_PAGE_URL}` (Task 2), `app.__version__` (Task 1)
- Produces: `MainWindow.push_live_event({"type": "update_available", "version": str})` handled; `MainWindow.update_notice_var: tk.StringVar`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_start_update_check_runs_in_background_and_reports_via_callback(monkeypatch):
    monkeypatch.setattr(main.update_check, "check_for_update", lambda cur, url: "0.2.0")
    reported = []

    main._start_update_check(on_update_available=reported.append)

    import time
    deadline = time.time() + 2
    while not reported and time.time() < deadline:
        time.sleep(0.01)

    assert reported == ["0.2.0"]


def test_start_update_check_calls_nothing_when_no_update(monkeypatch):
    monkeypatch.setattr(main.update_check, "check_for_update", lambda cur, url: None)
    reported = []

    thread = main._start_update_check(on_update_available=reported.append)
    thread.join(timeout=2)

    assert reported == []
```

Append to `tests/ui/test_window.py`:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_available_event_shows_notice_with_version():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "update_available", "version": "0.2.0"})
    _pump_until(root, lambda: window.update_notice_var.get() != "")

    assert "0.2.0" in window.update_notice_var.get()
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_notice_click_opens_releases_page_when_configured(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module
    monkeypatch.setattr(window_module.update_check, "RELEASES_PAGE_URL", "https://example/releases")
    opened = []
    monkeypatch.setattr(window_module.webbrowser, "open", opened.append)
    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_update_notice_click()

    assert opened == ["https://example/releases"]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_notice_click_no_op_when_url_blank(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module
    monkeypatch.setattr(window_module.update_check, "RELEASES_PAGE_URL", "")
    opened = []
    monkeypatch.setattr(window_module.webbrowser, "open", opened.append)
    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_update_notice_click()

    assert opened == []
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v -k update_check`
Run: `pytest tests/ui/test_window.py -v -k update_available`
Expected: FAIL — `main._start_update_check`, `main.update_check` (the
import), and `MainWindow.update_notice_var` don't exist yet.

- [ ] **Step 3: Write the implementation**

Add to the imports in `app/main.py`:

```python
import threading

from app import update_check
from app import __version__
```

(`import threading` may already be present — check first.)

Add this function above `def main() -> None:`:

```python
def _start_update_check(on_update_available) -> threading.Thread:
    def _worker():
        new_version = update_check.check_for_update(__version__, update_check.RELEASES_API_URL)
        if new_version:
            on_update_available(new_version)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
```

Call it once `window` exists in `main()` (after `window_ref["window"] = window`,
which is already where `push_live_event` becomes reachable for the live
session wiring):

```python
    window_ref["window"] = window
    _start_update_check(
        on_update_available=lambda v: window.push_live_event({"type": "update_available", "version": v})
    )
```

Add `import webbrowser` to the top of `app/ui/window.py`, and
`from app import update_check`.

In `app/ui/window.py`, add a notice label next to the existing
`live_warning_label` / `recording_pulse_label` in `_build_recording_frame`,
clickable when a URL is actually configured (a blank `RELEASES_PAGE_URL`
makes the click a no-op rather than opening an empty/broken link):

```python
        self.update_notice_var = tk.StringVar()
        self.update_notice_label = tk.Label(parent, textvariable=self.update_notice_var, fg="blue", cursor="hand2")
        self.update_notice_label.pack(anchor="w")
        self.update_notice_label.bind("<Button-1>", self._handle_update_notice_click)
```

Add this method to `MainWindow`:

```python
    def _handle_update_notice_click(self, event=None) -> None:
        if update_check.RELEASES_PAGE_URL:
            webbrowser.open(update_check.RELEASES_PAGE_URL)
```

In `_drain_live_events`, add a new branch:

```python
                elif event["type"] == "update_available":
                    self.update_notice_var.set(f"Update tersedia: v{event['version']} -- klik untuk buka halaman unduh")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py tests/ui/test_window.py -v`
Expected: all passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/ui/window.py tests/test_main.py tests/ui/test_window.py
git commit -m "feat(main): check for updates on startup, notify without blocking"
```

---

### Task 4: PyInstaller build configuration

**Files:**
- Create: `packaging/MeetingRecorder.spec`
- Create: `packaging/README.md`

This task has no pytest coverage — per the spec, the build pipeline itself
is outside pytest's scope. Each step below ends in a concrete command to
run and an observable result to check, standing in for the usual
test/implement/verify cycle.

- [ ] **Step 1: Write the PyInstaller spec file**

```python
# packaging/MeetingRecorder.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for pkg in ("torch", "ctranslate2", "faster_whisper", "pyannote.audio", "openvino", "optimum"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["../app/main.py"],
    pathex=["../"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MeetingRecorder",
    console=False,  # --windowed: no console window for a Tk GUI app
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="MeetingRecorder",
)
```

- [ ] **Step 2: Write the packaging README**

```markdown
<!-- packaging/README.md -->
# Building the Windows installer

1. `pip install pyinstaller`
2. Download a static `ffmpeg.exe` build (e.g. from gyan.dev's builds page)
   and place it at `packaging/ffmpeg/ffmpeg.exe`.
3. From `packaging/`, run: `pyinstaller MeetingRecorder.spec`
4. Copy `packaging/ffmpeg/` into `dist/MeetingRecorder/ffmpeg/` so
   `app.main.prepend_bundled_ffmpeg_to_path()` finds it next to the built
   executable at runtime.
5. Proceed to the Inno Setup step (see `packaging/installer.iss`) to
   produce the final `MeetingRecorderSetup-<version>.exe`.

Model weights are NOT bundled -- they download automatically the first
time Transkrip/Ringkasan is used, exactly like running from source.
```

- [ ] **Step 3: Run PyInstaller and verify the build**

Run (from `packaging/`, with `ffmpeg.exe` already placed per Step 2):
```
pyinstaller MeetingRecorder.spec
```
Expected: `dist/MeetingRecorder/MeetingRecorder.exe` exists.

Run: `dist\MeetingRecorder\MeetingRecorder.exe`
Expected: the app starts (may take longer than `python -m app.main` the
first time due to extraction) and shows the same window as running from
source. If the storage-backend plan is implemented, the first-run wizard
should appear (no `config.json` exists yet in `%LOCALAPPDATA%` for this
fresh build).

- [ ] **Step 4: Commit**

```bash
git add packaging/MeetingRecorder.spec packaging/README.md
git commit -m "build: add PyInstaller spec for the Windows build"
```

(Do not commit `dist/`, `build/`, or the vendored `ffmpeg.exe` binary
itself — add `packaging/ffmpeg/`, `dist/`, and `build/` to `.gitignore` if
they aren't already covered by an existing rule.)

---

### Task 5: Inno Setup installer script

**Files:**
- Create: `packaging/installer.iss`

No pytest coverage (same reasoning as Task 4).

- [ ] **Step 1: Write the Inno Setup script**

```ini
; packaging/installer.iss
[Setup]
AppName=Meeting Recorder
AppVersion=0.1.0
DefaultDirName={autopf}\MeetingRecorder
DefaultGroupName=Meeting Recorder
OutputBaseFilename=MeetingRecorderSetup-0.1.0
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\MeetingRecorder.exe

[Files]
Source: "dist\MeetingRecorder\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Meeting Recorder"; Filename: "{app}\MeetingRecorder.exe"
Name: "{group}\Uninstall Meeting Recorder"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\MeetingRecorder.exe"; Description: "Jalankan Meeting Recorder"; Flags: postinstall nowait skipifsilent
```

(`AppVersion` and `OutputBaseFilename` need bumping by hand alongside
`app/__init__.py::__version__` and `pyproject.toml`'s `version` — three
places to keep in sync per release, noted here so it isn't a surprise.)

- [ ] **Step 2: Build the installer and verify it**

Run (with Inno Setup installed and `dist/MeetingRecorder/` already built
per Task 4):
```
iscc packaging\installer.iss
```
Expected: `packaging/Output/MeetingRecorderSetup-0.1.0.exe` exists.

Run the resulting installer on a clean Windows machine (not the dev
machine — the whole point is proving it works without Python/venv
present). Expected: Start Menu shortcut created, app launches, appears in
Settings > Apps as "Meeting Recorder" with a working uninstaller.

- [ ] **Step 3: Commit**

```bash
git add packaging/installer.iss
git commit -m "build: add Inno Setup script for the final installer"
```

---

### Task 6: Full regression pass + manual distribution checklist

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass, no regressions, across the whole plan series.

- [ ] **Step 2: Manual verification checklist (per spec §7)**

On a clean machine (no Python, no venv):
- [ ] Install via `MeetingRecorderSetup-<version>.exe`
- [ ] First launch shows the setup wizard (storage-backend plan)
- [ ] ffmpeg is detected without any manual install (`check_ffmpeg_available()`
  returns True on first run — confirm via `logs/app.log`, no warning line)
- [ ] Recording + transcription work end-to-end
- [ ] Uninstalling via Settings > Apps removes the install directory but
  leaves `%LOCALAPPDATA%\MeetingRecorder\` (config, database, recordings)
  untouched

- [ ] **Step 3: Fill in real Releases URLs once a release exists**

The click-to-open behavior is already implemented (Task 3) and guarded on
`RELEASES_PAGE_URL` being non-empty — nothing left to build here. Once
this repo has an actual tagged release (GitHub or the UGM GitLab
instance), just update the two constants in `app/update_check.py`
(`RELEASES_API_URL`, `RELEASES_PAGE_URL`) from empty strings to the real
endpoints. This is a one-line-each config change, deliberately deferred
past this plan since there is no release to point at yet.

- [ ] **Step 4: Commit (if any step required fixes)**

```bash
git add -A
git commit -m "fix: address regressions found in full verification pass"
```

(Skip this commit entirely if no changes were needed.)
