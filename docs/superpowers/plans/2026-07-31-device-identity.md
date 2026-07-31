# Device Identity (`device_id`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp every `Meeting` with a stable per-install `device_id` (UUID) and an editable human-readable `device_label`, so meetings can be attributed to the device/person that recorded them once data starts getting shared across devices.

**Architecture:** Builds directly on the [storage backend plan](2026-07-31-storage-backend-setup-wizard.md) — `device_id`/`device_label` live in the same `config.json`, are collected via one new field on the existing `SetupWizard`, and flow through `Settings` → `RecorderController.start_meeting()` → `repository.create_meeting()` → the `Meeting` row. No new tables, no new UI surfaces beyond one wizard field and one Riwayat column.

**Tech Stack:** Same as the storage backend plan (SQLAlchemy async, Tkinter, pytest) plus stdlib `uuid` and `socket`.

## Global Constraints

- **Depends on the storage backend plan being implemented first** — this plan assumes `app/settings_store.py`, the `Settings.storage_backend`/`database_url` changes, and `app/ui/setup_wizard.py` already exist exactly as that plan produces them.
- `device_id` is generated once per install and never changes automatically — verify this explicitly in tests, not just by inspection.
- Existing tests that call `create_meeting()`/`start_meeting()` without device args must keep passing unmodified (`device_id`/`device_label` default to `None`).

---

### Task 1: `Meeting.device_id` / `Meeting.device_label` columns

**Files:**
- Modify: `app/storage/models.py`
- Modify: `tests/storage/test_models.py`

**Interfaces:**
- Produces: `Meeting.device_id: str | None`, `Meeting.device_label: str | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/storage/test_models.py` (follow the existing style in that
file — construct a `Meeting` directly and assert on its attributes):

```python
def test_meeting_device_fields_default_to_none():
    meeting = Meeting(title="Rapat", device_id=None, device_label=None)
    assert meeting.device_id is None
    assert meeting.device_label is None


def test_meeting_accepts_device_fields():
    meeting = Meeting(title="Rapat", device_id="abc123", device_label="Laptop Budi")
    assert meeting.device_id == "abc123"
    assert meeting.device_label == "Laptop Budi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_models.py -v -k device`
Expected: FAIL — `TypeError: 'device_id' is an invalid keyword argument for Meeting`

- [ ] **Step 3: Write the implementation**

In `app/storage/models.py`, add two columns to the `Meeting` class, right
after the existing `failed_stage` column:

```python
    failed_stage: Mapped[str | None] = mapped_column(default=None)
    device_id: Mapped[str | None] = mapped_column(default=None)
    device_label: Mapped[str | None] = mapped_column(default=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_models.py -v -k device`
Expected: 2 passed

- [ ] **Step 5: Add the existing Postgres database's column manually**

This repo's own Postgres instance (used in dev mode) already has a
`meetings` table — `Base.metadata.create_all()` (called from
`app/storage/db.py::init_db`) only creates missing *tables*, not missing
*columns* on tables that already exist. Without this step, dev mode will
break the first time `create_meeting()` is called with the new columns.

Run against the dev database (credentials from the local `.env`):

```sql
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS device_id VARCHAR;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS device_label VARCHAR;
```

Any fresh SQLite database (every packaged install) doesn't need this —
`create_all()` creates the whole table from scratch with both columns
already present.

- [ ] **Step 6: Commit**

```bash
git add app/storage/models.py tests/storage/test_models.py
git commit -m "feat(models): add device_id/device_label to Meeting"
```

---

### Task 2: `settings_store` — generate-once device_id persistence

**Files:**
- Modify: `app/settings_store.py`
- Modify: `tests/test_settings_store.py`

**Interfaces:**
- Consumes: `load_packaged_config()`, `config_dir()`, `config_path()` (all already in `app/settings_store.py` from the storage backend plan)
- Produces: `save_packaged_config(data: dict) -> None` now guarantees `data["device_id"]` is set (preserved from any existing config, or freshly generated) before writing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings_store.py -v -k device_id`
Expected: FAIL — `saved["device_id"]` is absent (`KeyError`), since
`save_packaged_config` doesn't generate or preserve one yet.

- [ ] **Step 3: Write the implementation**

Add `import uuid` to the top of `app/settings_store.py`, and replace
`save_packaged_config`:

```python
def save_packaged_config(data: dict) -> None:
    if not data.get("device_id"):
        existing = load_packaged_config() or {}
        data["device_id"] = existing.get("device_id") or uuid.uuid4().hex
    config_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings_store.py -v`
Expected: all passed (12 total: 9 from the storage backend plan + 3 new)

- [ ] **Step 5: Commit**

```bash
git add app/settings_store.py tests/test_settings_store.py
git commit -m "feat(settings): generate device_id once, preserve it across resaves"
```

---

### Task 3: `Settings.device_id` / `Settings.device_label`

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.device_id: str = ""`, `Settings.device_label: str = ""`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_packaged_mode_reads_device_identity_from_config_json(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no .env -> packaged mode
    from app import settings_store
    settings_store.save_packaged_config({
        "storage_backend": "sqlite", "device_label": "Laptop Budi",
    })
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.device_id  # generated by save_packaged_config
    assert settings.device_label == "Laptop Budi"


def test_dev_mode_device_identity_defaults_to_empty(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("STORAGE_BACKEND=postgres\n")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.device_id == ""
    assert settings.device_label == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v -k device`
Expected: FAIL — `Settings` has no `device_id`/`device_label` fields yet.

- [ ] **Step 3: Write the implementation**

In `app/config.py`, add two fields to `Settings`, next to the existing
`hf_token`:

```python
    hf_token: str = ""
    device_id: str = ""
    device_label: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): expose device_id/device_label on Settings"
```

---

### Task 4: Wizard "Nama perangkat" field

**Files:**
- Modify: `app/ui/setup_wizard.py`
- Modify: `tests/ui/test_setup_wizard.py`

**Interfaces:**
- Produces: `SetupWizard.device_label_var: tk.StringVar` (prefilled from `initial.get("device_label")` or `socket.gethostname()`); `_on_submit()`'s saved data now includes `device_label`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_setup_wizard.py`:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_device_label_defaults_to_hostname(monkeypatch):
    monkeypatch.setattr(setup_wizard_module.socket, "gethostname", lambda: "DESKTOP-XYZ")
    root = tk.Tk()

    wizard = SetupWizard(parent=root)

    assert wizard.device_label_var.get() == "DESKTOP-XYZ"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_device_label_prefilled_from_initial():
    root = tk.Tk()

    wizard = SetupWizard(parent=root, initial={"device_label": "Laptop Budi"})

    assert wizard.device_label_var.get() == "Laptop Budi"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_includes_device_label_and_falls_back_to_hostname_when_blank(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)
    monkeypatch.setattr(setup_wizard_module.socket, "gethostname", lambda: "DESKTOP-XYZ")
    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.device_label_var.set("")  # user cleared the field

    wizard._submit_button.invoke()

    assert saved["device_label"] == "DESKTOP-XYZ"
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_setup_wizard.py -v -k device_label`
Expected: FAIL — `AttributeError: 'SetupWizard' object has no attribute 'device_label_var'`

- [ ] **Step 3: Write the implementation**

Add `import socket` to the top of `app/ui/setup_wizard.py`.

Add the field to `SetupWizard.__init__`, right after the storage
radio buttons and before the `_postgres_frame` block:

```python
        tk.Label(self.window, text="Nama perangkat:").pack(anchor="w")
        self.device_label_var = tk.StringVar(
            value=initial.get("device_label") or socket.gethostname()
        )
        tk.Entry(self.window, textvariable=self.device_label_var).pack(fill="x")
```

In `_on_submit`, add the device label to `data` (falls back to hostname if
the user blanked the field):

```python
    data = {
        "storage_backend": self.storage_var.get(),
        "groq_api_key": self.groq_var.get(),
        "hf_token": self.hf_var.get(),
        "device_label": self.device_label_var.get() or socket.gethostname(),
    }
```

- [ ] **Step 4: Fix the pre-existing test broken by the new `data` key**

`test_submit_sqlite_saves_config_without_connection_check` (added in the
storage backend plan) asserts `saved` equals an exact dict literal that
doesn't include `device_label` — it will now fail because the real
`_on_submit` adds that key. Update it to set the field explicitly (so the
test doesn't depend on the real machine's hostname) and expect it back:

```python
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
    wizard.device_label_var.set("test-device")

    wizard._submit_button.invoke()

    assert make_engine_calls == []  # sqlite never needs a connectivity check
    assert saved == {
        "storage_backend": "sqlite", "groq_api_key": "gk", "hf_token": "hf",
        "device_label": "test-device",
    }
    root.destroy()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: all passed (the fixed test plus the 3 new ones from Step 1)

- [ ] **Step 6: Commit**

```bash
git add app/ui/setup_wizard.py tests/ui/test_setup_wizard.py
git commit -m "feat(ui): collect device label in the setup wizard"
```

---

### Task 5: `repository.create_meeting()` device fields

**Files:**
- Modify: `app/storage/repository.py`
- Modify: `tests/storage/test_repository.py`

**Interfaces:**
- Produces: `create_meeting(session, title, scheduled_time, recording_dir=None, device_id=None, device_label=None) -> Meeting`

- [ ] **Step 1: Write the failing test**

Append to `tests/storage/test_repository.py`:

```python
def test_create_meeting_stores_device_identity():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat", None, device_id="abc123", device_label="Laptop Budi",
            )
            await session.commit()
            meeting_id = meeting.id
        async with session_factory() as session:
            fetched = await session.get(Meeting, meeting_id)
            return fetched.device_id, fetched.device_label

    device_id, device_label = asyncio.run(scenario())
    assert device_id == "abc123"
    assert device_label == "Laptop Budi"


def test_create_meeting_without_device_args_leaves_fields_none():
    async def scenario():
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_db(engine)
        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            meeting = await repo.create_meeting(session, "Rapat", None)
            await session.commit()
            return meeting.device_id, meeting.device_label

    device_id, device_label = asyncio.run(scenario())
    assert device_id is None
    assert device_label is None
```

Check the imports at the top of `tests/storage/test_repository.py`: if
`from app.storage.models import Meeting` (or an equivalent import that
brings `Meeting` into scope) isn't already present, add it — the file's
existing imports may only cover models used by earlier tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_repository.py -v -k device_identity`
Expected: FAIL — `create_meeting()` doesn't accept `device_id`/`device_label` kwargs yet.

- [ ] **Step 3: Write the implementation**

In `app/storage/repository.py`, replace `create_meeting`:

```python
async def create_meeting(
    session: AsyncSession, title: str, scheduled_time: datetime | None,
    recording_dir: str | None = None, device_id: str | None = None,
    device_label: str | None = None,
) -> Meeting:
    meeting = Meeting(
        title=title, scheduled_time=scheduled_time, status="scheduled",
        recording_dir=recording_dir, device_id=device_id, device_label=device_label,
    )
    session.add(meeting)
    await session.flush()
    return meeting
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_repository.py -v`
Expected: all passed, no regressions in the other `create_meeting` callers
in that file (they don't pass device args, so they still get `None`/`None`).

- [ ] **Step 5: Commit**

```bash
git add app/storage/repository.py tests/storage/test_repository.py
git commit -m "feat(repository): store device_id/device_label on create_meeting"
```

---

### Task 6: `RecorderController` → `create_meeting` device passthrough

**Files:**
- Modify: `app/ui/controller.py`
- Modify: `app/main.py`
- Modify: `tests/ui/test_controller.py`

**Interfaces:**
- Consumes: `repo.create_meeting(..., device_id=..., device_label=...)` (Task 5)
- Produces: `RecorderController.__init__(..., device_id: str | None = None, device_label: str | None = None)`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_controller.py`. First, modify the `_make_controller`
helper (near the top of the file) to accept and forward the two new
params:

```python
def _make_controller(tmp_path, session_factory, transcribe_fn=_noop_transcribe_fn,
                      summarize_fn=_noop_summarize_fn, recorder_cls=FakeRecorder,
                      live_session_factory=None, device_id=None, device_label=None):
    return RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: recorder_cls(mic, speaker),
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
        device_id=device_id,
        device_label=device_label,
    )
```

Then add a new test:

```python
def test_start_meeting_stamps_device_identity(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(
        tmp_path, session_factory, device_id="abc123", device_label="Laptop Budi",
    )

    meeting_id = controller.start_meeting("Rapat Device")

    async def _get():
        async with session_factory() as session:
            from app.storage.models import Meeting
            return await session.get(Meeting, meeting_id)

    meeting = asyncio.run(_get())
    assert meeting.device_id == "abc123"
    assert meeting.device_label == "Laptop Budi"
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `pytest tests/ui/test_controller.py -v -k device_identity`
Expected: FAIL — `RecorderController.__init__() got an unexpected keyword argument 'device_id'`

- [ ] **Step 3: Write the implementation**

In `app/ui/controller.py`, modify `RecorderController.__init__` — add two
params and store them:

```python
    def __init__(
        self,
        session_factory,
        recorder_factory: Callable,
        transcribe_fn: Callable[..., Awaitable],
        summarize_fn: Callable[..., Awaitable],
        recordings_dir: Path,
        live_session_factory: Callable[[Path, Path, Path], object] | None = None,
        device_id: str | None = None,
        device_label: str | None = None,
    ):
        self._session_factory = session_factory
        self._recorder_factory = recorder_factory
        self._transcribe_fn = transcribe_fn
        self._summarize_fn = summarize_fn
        self._recordings_dir = recordings_dir
        self._live_session_factory = live_session_factory
        self._device_id = device_id
        self._device_label = device_label
        self.state = "idle"
        self.error_message: str | None = None
        self._meeting_id: int | None = None
        self._meeting_title: str | None = None
        self._recorder = None
        self._live_session = None
```

In `start_meeting()`, pass the two fields through to `repo.create_meeting`:

```python
        async def _create():
            async with self._session_factory() as session:
                meeting = await repo.create_meeting(
                    session, title, datetime.now(timezone.utc), recording_dir=str(meeting_dir),
                    device_id=self._device_id, device_label=self._device_label,
                )
                await repo.start_recording(session, meeting.id)
                await session.commit()
                return meeting.id
```

In `app/main.py`, find where `RecorderController(...)` is constructed and
add the two new args, sourced from `settings` (already in scope at that
point in `main()`):

```python
    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=settings.recordings_dir,
        live_session_factory=live_session_factory,
        device_id=settings.device_id,
        device_label=settings.device_label,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_controller.py -v`
Expected: all passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ui/controller.py app/main.py tests/ui/test_controller.py
git commit -m "feat(controller): stamp device_id/device_label on every new meeting"
```

---

### Task 7: "Perangkat" column in Riwayat

**Files:**
- Modify: `app/ui/history_view.py`
- Modify: `tests/ui/test_history_view.py`

**Interfaces:**
- Consumes: `meeting.device_label` (already on the `Meeting` model via Task 1; `FakeController`'s `_meeting()` helper in the test file needs a `device_label` field)

- [ ] **Step 1: Write the failing test**

In `tests/ui/test_history_view.py`, modify the `_meeting()` helper to
accept and pass through `device_label`:

```python
def _meeting(id, title, status, error_message=None, failed_stage=None, device_label=None):
    return SimpleNamespace(
        id=id, title=title, status=status,
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        error_message=error_message, failed_stage=failed_stage, device_label=device_label,
    )
```

Add new tests:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_device_label_column():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded", device_label="Laptop Budi")])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[3] == "Laptop Budi"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_fallback_for_unknown_device():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded", device_label=None)])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[3] == "Tidak diketahui"
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_history_view.py -v -k device_label`
Expected: FAIL — `IndexError: tuple index out of range` (only 3 columns exist)

- [ ] **Step 3: Write the implementation**

In `app/ui/history_view.py`, modify the `Treeview` construction:

```python
        self._tree = ttk.Treeview(self, columns=("title", "date", "status", "device"), show="headings", height=10)
        self._tree.heading("title", text="Judul")
        self._tree.heading("date", text="Tanggal")
        self._tree.heading("status", text="Status")
        self._tree.heading("device", text="Perangkat")
```

In `refresh()`, add the device value to the inserted row:

```python
        for meeting in meetings:
            date_str = to_wib(meeting.start_time).strftime("%Y-%m-%d %H:%M") if meeting.start_time else "-"
            iid = str(meeting.id)
            self._tree.insert("", "end", iid=iid, values=(
                meeting.title, date_str, _STATUS_LABELS.get(meeting.status, meeting.status),
                meeting.device_label or "Tidak diketahui",
            ))
            self._meetings_by_iid[iid] = meeting
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_history_view.py -v`
Expected: all passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ui/history_view.py tests/ui/test_history_view.py
git commit -m "feat(ui): show Perangkat column in Riwayat"
```

---

### Task 8: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass — baseline count from before this plan (already
including the storage backend plan's tests), plus every test added in
Tasks 1-7.

- [ ] **Step 2: Manually verify against the real dev database**

Run: `python -m app.main` from the dev checkout. Confirm the ALTER TABLE
from Task 1 Step 5 was actually applied (start a meeting; if it wasn't,
this fails loudly with a Postgres "column does not exist" error, not
silently). Confirm the new meeting shows a "Perangkat" column value in
Riwayat (will read "Tidak diketahui" since dev mode's `device_label`
defaults to empty — this is expected per Task 3, not a bug).

- [ ] **Step 3: Commit (if Step 2 required any fixes)**

```bash
git add -A
git commit -m "fix: address regressions found in full verification pass"
```

(Skip this commit entirely if Step 2 needed no changes.)
