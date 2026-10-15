# MinIO File & Metadata Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A manual, bidirectional "Sync Sekarang" button that pushes locally-recorded meetings (files + a metadata manifest) to MinIO and pulls other devices' manifests into the local database, so meetings become visible across independent per-device SQLite installs without needing a shared Postgres server.

**Architecture:** `app/sync/minio_client.py` owns all MinIO I/O (lazy-imported, mocked via `sys.modules` in tests) and pure manifest build/parse helpers. `HistoryView` gets one new global "Sync Sekarang" button and hides processing actions (not view/download/delete) for meetings owned by another device.

**Tech Stack:** `minio` (new dependency, official S3-compatible client), stdlib `json`/`datetime`, existing SQLAlchemy async session pattern, Tkinter.

## Global Constraints

- **Depends on the storage backend, device identity, AND (for the wizard field) their combined state already being implemented** — this plan assumes `Settings.device_id`, `Meeting.device_id`/`device_label`, `app/ui/setup_wizard.py`, and `app/settings_store.py` already exist exactly as those plans produce them.
- Sync is 100% manual and opt-in — `is_configured(settings)` must gate every code path that could touch MinIO; empty config means zero network activity, not just a disabled button.
- Never download WAV files for meetings owned by another device — only `manifest.json` (metadata) and, on demand, `mom.docx`.
- A meeting record for `device_id != local device_id` must never be writable via Transkrip/Ringkasan/Coba Lagi — verify this with a test, not just by hiding buttons (hiding a button is a UI nicety; the controller methods themselves stay reachable and are not this plan's job to lock down further — noted explicitly in Task 9).

---

### Task 1: `Meeting.synced_at` column + `minio` dependency

**Files:**
- Modify: `app/storage/models.py`
- Modify: `tests/storage/test_models.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `Meeting.synced_at: datetime | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/storage/test_models.py`:

```python
def test_meeting_synced_at_defaults_to_none():
    meeting = Meeting(title="Rapat")
    assert meeting.synced_at is None


def test_meeting_accepts_synced_at():
    from datetime import datetime, timezone
    ts = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    meeting = Meeting(title="Rapat", synced_at=ts)
    assert meeting.synced_at == ts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_models.py -v -k synced_at`
Expected: FAIL — `TypeError: 'synced_at' is an invalid keyword argument for Meeting`

- [ ] **Step 3: Write the implementation**

In `app/storage/models.py`, add one column to `Meeting`, after `device_label`
(added by the device identity plan):

```python
    device_label: Mapped[str | None] = mapped_column(default=None)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_models.py -v -k synced_at`
Expected: 2 passed

- [ ] **Step 5: Add the column to the real dev Postgres database**

Same reasoning as the device identity plan's Task 1 Step 5 —
`create_all()` won't add a column to an already-existing table:

```sql
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
```

- [ ] **Step 6: Add the `minio` dependency**

In `pyproject.toml`, add `"minio"` to the `dependencies` list (alphabetical
position doesn't matter — the existing list isn't strictly sorted):

```toml
    "silero-vad",
    "tzdata",
    "minio",
]
```

Run: `pip install -e .`
Expected: `minio` and its transitive dependencies install without error.

- [ ] **Step 7: Commit**

```bash
git add app/storage/models.py tests/storage/test_models.py pyproject.toml
git commit -m "feat(models): add Meeting.synced_at, add minio dependency"
```

---

### Task 2: `Settings` MinIO fields + `is_configured()`

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.minio_endpoint: str = ""`, `Settings.minio_access_key: str = ""`, `Settings.minio_secret_key: str = ""`, `Settings.minio_bucket: str = ""`, `Settings.minio_is_configured -> bool` (property)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_minio_is_configured_false_when_any_field_blank(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("STORAGE_BACKEND=postgres\nMINIO_ENDPOINT=play.min.io\n")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.minio_endpoint == "play.min.io"
    assert settings.minio_is_configured is False  # access/secret/bucket still blank


def test_minio_is_configured_true_when_all_fields_set(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "STORAGE_BACKEND=postgres\n"
        "MINIO_ENDPOINT=play.min.io\nMINIO_ACCESS_KEY=ak\n"
        "MINIO_SECRET_KEY=sk\nMINIO_BUCKET=meetings\n"
    )
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.minio_is_configured is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v -k minio`
Expected: FAIL — `Settings` has no MinIO fields yet.

- [ ] **Step 3: Write the implementation**

In `app/config.py`, add four fields to `Settings`, next to
`device_label`:

```python
    device_label: str = ""
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = ""

    @property
    def minio_is_configured(self) -> bool:
        return bool(
            self.minio_endpoint and self.minio_access_key
            and self.minio_secret_key and self.minio_bucket
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): add MinIO settings and is-configured check"
```

---

### Task 3: Wizard MinIO expander

**Files:**
- Modify: `app/ui/setup_wizard.py`
- Modify: `tests/ui/test_setup_wizard.py`

**Interfaces:**
- Produces: `SetupWizard.minio_endpoint_var`, `.minio_access_key_var`, `.minio_secret_key_var`, `.minio_bucket_var` (all `tk.StringVar`); `_on_submit()`'s saved data includes all four (empty string if left blank — never validated/connection-checked, matching "default off")

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_setup_wizard.py`:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_minio_fields_prefilled_from_initial():
    root = tk.Tk()

    wizard = SetupWizard(parent=root, initial={
        "minio_endpoint": "play.min.io", "minio_access_key": "ak",
        "minio_secret_key": "sk", "minio_bucket": "meetings",
    })

    assert wizard.minio_endpoint_var.get() == "play.min.io"
    assert wizard.minio_access_key_var.get() == "ak"
    assert wizard.minio_secret_key_var.get() == "sk"
    assert wizard.minio_bucket_var.get() == "meetings"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_includes_blank_minio_fields_by_default(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)
    root = tk.Tk()
    wizard = SetupWizard(parent=root)

    wizard._submit_button.invoke()

    assert saved["minio_endpoint"] == ""
    assert saved["minio_access_key"] == ""
    assert saved["minio_secret_key"] == ""
    assert saved["minio_bucket"] == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_never_checks_minio_connectivity(monkeypatch):
    """MinIO config is never validated at submit time -- default off means
    zero network activity, not a connectivity check that could hang/fail."""
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)
    minio_client_calls = []
    monkeypatch.setattr(
        setup_wizard_module, "Minio", lambda *a, **k: minio_client_calls.append(True), raising=False,
    )
    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.minio_endpoint_var.set("play.min.io")
    wizard.minio_access_key_var.set("ak")
    wizard.minio_secret_key_var.set("sk")
    wizard.minio_bucket_var.set("meetings")

    wizard._submit_button.invoke()

    assert minio_client_calls == []
    assert saved["minio_endpoint"] == "play.min.io"
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_setup_wizard.py -v -k minio`
Expected: FAIL — `AttributeError: 'SetupWizard' object has no attribute 'minio_endpoint_var'`

- [ ] **Step 3: Write the implementation**

In `app/ui/setup_wizard.py`, add the four fields to `SetupWizard.__init__`,
after the HF_TOKEN row and before the error label:

```python
        tk.Label(self.window, text="Sinkronisasi MinIO (lanjutan, opsional):").pack(anchor="w")
        minio_frame = tk.Frame(self.window)
        minio_frame.pack(fill="x")
        self.minio_endpoint_var = tk.StringVar(value=initial.get("minio_endpoint", ""))
        self.minio_access_key_var = tk.StringVar(value=initial.get("minio_access_key", ""))
        self.minio_secret_key_var = tk.StringVar(value=initial.get("minio_secret_key", ""))
        self.minio_bucket_var = tk.StringVar(value=initial.get("minio_bucket", ""))
        for label, var in [
            ("Endpoint", self.minio_endpoint_var), ("Access Key", self.minio_access_key_var),
            ("Secret Key", self.minio_secret_key_var), ("Bucket", self.minio_bucket_var),
        ]:
            row = tk.Frame(minio_frame)
            row.pack(fill="x")
            tk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
```

In `_on_submit`, add the four fields to `data` (no validation — always
included, empty string if blank):

```python
        "device_label": self.device_label_var.get() or socket.gethostname(),
        "minio_endpoint": self.minio_endpoint_var.get(),
        "minio_access_key": self.minio_access_key_var.get(),
        "minio_secret_key": self.minio_secret_key_var.get(),
        "minio_bucket": self.minio_bucket_var.get(),
    }
```

(This replaces the closing `}` of the existing `data = {...}` dict literal
— add these four lines as the last entries before it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_setup_wizard.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/ui/setup_wizard.py tests/ui/test_setup_wizard.py
git commit -m "feat(ui): add MinIO sync fields to setup wizard"
```

---

### Task 4: `app/sync/minio_client.py` — manifest build/parse (pure functions)

**Files:**
- Create: `app/sync/__init__.py` (empty)
- Create: `app/sync/minio_client.py`
- Test: `tests/sync/__init__.py` (empty)
- Test: `tests/sync/test_minio_client.py`

**Interfaces:**
- Produces: `build_manifest(meeting, segments, speakers_by_id, summary) -> dict`, `manifest_object_prefix(device_id: str, meeting_dir_uuid: str) -> str`, `is_configured(settings) -> bool` (delegates to `settings.minio_is_configured`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/sync/test_minio_client.py
from datetime import datetime, timezone

from app.storage.models import Speaker, Summary, TranscriptSegment, Meeting
from app.sync import minio_client


def test_build_manifest_includes_meeting_fields_and_final_segments_only():
    meeting = Meeting(
        id=1, title="Rapat Rilis", device_id="dev1", device_label="Laptop Budi",
        status="completed",
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc),
    )
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=None, source="mic",
                           start_ms=0, end_ms=900, text="Halo", is_final=True),
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=900, end_ms=1500, text="Draft", is_final=False),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["title"] == "Rapat Rilis"
    assert manifest["device_id"] == "dev1"
    assert manifest["device_label"] == "Laptop Budi"
    assert manifest["status"] == "completed"
    assert manifest["start_time"] == "2026-07-31T09:00:00+00:00"
    assert len(manifest["segments"]) == 1  # the draft (is_final=False) is excluded
    assert manifest["segments"][0] == {
        "speaker_label": "Anda", "source": "mic", "start_ms": 0, "end_ms": 900, "text": "Halo",
    }
    assert manifest["summary"] is None


def test_build_manifest_resolves_speaker_labels_for_non_mic_segments():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="recorded")
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=0, end_ms=500, text="Mari mulai", is_final=True),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["segments"][0]["speaker_label"] == "Speaker 1"


def test_build_manifest_includes_summary_when_present():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(
        meeting_id=1, mom_json='{"x": 1}', docx_path="/some/path/mom.docx",
        groq_model="openai/gpt-oss-120b", status="ready",
    )

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"] == {
        "mom_json": '{"x": 1}', "has_docx": True,
        "groq_model": "openai/gpt-oss-120b", "status": "ready",
    }


def test_build_manifest_summary_has_docx_false_when_docx_path_is_none():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(meeting_id=1, mom_json="{}", docx_path=None, groq_model="m", status="ready")

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"]["has_docx"] is False


def test_manifest_object_prefix_shape():
    assert minio_client.manifest_object_prefix("dev1", "uuid123") == "dev1/uuid123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/sync/test_minio_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sync'`

- [ ] **Step 3: Write the implementation**

Create `app/sync/__init__.py` (empty file) and `tests/sync/__init__.py`
(empty file).

```python
# app/sync/minio_client.py
def is_configured(settings) -> bool:
    return settings.minio_is_configured


def manifest_object_prefix(device_id: str, meeting_dir_uuid: str) -> str:
    return f"{device_id}/{meeting_dir_uuid}"


def build_manifest(meeting, segments, speakers_by_id: dict, summary) -> dict:
    def _label(seg):
        if seg.speaker_id is None:
            return "Anda"
        return speakers_by_id[seg.speaker_id].label

    return {
        "title": meeting.title,
        "scheduled_time": meeting.scheduled_time.isoformat() if meeting.scheduled_time else None,
        "start_time": meeting.start_time.isoformat() if meeting.start_time else None,
        "end_time": meeting.end_time.isoformat() if meeting.end_time else None,
        "status": meeting.status,
        "device_id": meeting.device_id,
        "device_label": meeting.device_label,
        "segments": [
            {
                "speaker_label": _label(seg), "source": seg.source,
                "start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text,
            }
            for seg in segments if seg.is_final
        ],
        "summary": (
            {
                "mom_json": summary.mom_json, "has_docx": summary.docx_path is not None,
                "groq_model": summary.groq_model, "status": summary.status,
            }
            if summary is not None else None
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/sync/test_minio_client.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/sync tests/sync
git commit -m "feat(sync): manifest build helper for MinIO push/pull"
```

---

### Task 5: `push()`

**Files:**
- Modify: `app/sync/minio_client.py`
- Modify: `tests/sync/test_minio_client.py`

**Interfaces:**
- Consumes: `app.storage.repository` (existing), `build_manifest`/`manifest_object_prefix` (Task 4)
- Produces: `push(session_factory, settings) -> dict` (returns `{"uploaded": int, "manifests": int}`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/sync/test_minio_client.py`:

```python
import asyncio
import sys
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock

from app.storage.db import init_db, make_engine, make_session_factory
from app.storage import repository as repo


class FakeSettings:
    def __init__(self, device_id="dev1"):
        self.device_id = device_id
        self.minio_endpoint = "play.min.io"
        self.minio_access_key = "ak"
        self.minio_secret_key = "sk"
        self.minio_bucket = "meetings"
        self.minio_is_configured = True


def _fake_minio_module():
    module = ModuleType("minio")
    module.Minio = MagicMock()
    return module


def _make_db():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    return make_session_factory(engine)


def test_push_uploads_manifest_and_files_for_own_meetings_only(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    session_factory = _make_db()

    async def _seed():
        async with session_factory() as session:
            own = await repo.create_meeting(
                session, "Rapat Saya", None, recording_dir=str(tmp_path / "own"),
                device_id="dev1", device_label="Laptop Budi",
            )
            other = await repo.create_meeting(
                session, "Rapat Lain", None, recording_dir=str(tmp_path / "other"),
                device_id="dev2", device_label="Laptop Lain",
            )
            await session.commit()
            return own.id, other.id

    own_id, other_id = asyncio.run(_seed())
    (tmp_path / "own").mkdir()
    (tmp_path / "own" / "mic.wav").write_bytes(b"fake")

    result = minio_client.push(session_factory, FakeSettings())

    assert result["manifests"] == 1  # only the meeting owned by dev1
    fake_client.put_object.assert_called()  # manifest.json uploaded
    fake_client.fput_object.assert_called()  # mic.wav uploaded
    uploaded_keys = [c.args[1] for c in fake_client.put_object.call_args_list]
    assert any(k.startswith("dev1/") for k in uploaded_keys)
    assert not any(k.startswith("dev2/") for k in uploaded_keys)


def test_push_skips_re_uploading_files_when_already_synced(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    session_factory = _make_db()

    async def _seed_and_mark_synced():
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat", None, recording_dir=str(tmp_path / "own"),
                device_id="dev1", device_label="Laptop Budi",
            )
            await session.commit()
            meeting.synced_at = datetime.now(timezone.utc)
            await session.commit()

    asyncio.run(_seed_and_mark_synced())
    (tmp_path / "own").mkdir()
    (tmp_path / "own" / "mic.wav").write_bytes(b"fake")

    minio_client.push(session_factory, FakeSettings())

    fake_client.put_object.assert_called()  # manifest still re-uploaded
    fake_client.fput_object.assert_not_called()  # but not the WAV, already synced
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/sync/test_minio_client.py -v -k push`
Expected: FAIL — `AttributeError: module 'app.sync.minio_client' has no attribute 'push'`

- [ ] **Step 3: Write the implementation**

Add to `app/sync/minio_client.py` (new imports at the top, then the
function):

```python
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.storage.models import Meeting, Speaker, Summary, TranscriptSegment
from app.storage import repository as repo


def _client(settings):
    from minio import Minio
    return Minio(
        settings.minio_endpoint, access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
    )


def push(session_factory, settings) -> dict:
    import asyncio

    async def _run():
        client = _client(settings)
        manifests = 0
        uploaded = 0
        async with session_factory() as session:
            result = await session.execute(select(Meeting).where(Meeting.device_id == settings.device_id))
            meetings = list(result.scalars().all())
            for meeting in meetings:
                if not meeting.recording_dir:
                    continue
                seg_result = await session.execute(
                    select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id)
                )
                segments = list(seg_result.scalars().all())
                speaker_result = await session.execute(
                    select(Speaker).where(Speaker.meeting_id == meeting.id)
                )
                speakers_by_id = {s.id: s for s in speaker_result.scalars().all()}
                summary = await repo.get_summary(session, meeting.id)

                manifest = build_manifest(meeting, segments, speakers_by_id, summary)
                prefix = manifest_object_prefix(meeting.device_id, Path(meeting.recording_dir).name)
                client.put_object(
                    settings.minio_bucket, f"{prefix}/manifest.json",
                    io.BytesIO(json.dumps(manifest).encode("utf-8")),
                    length=len(json.dumps(manifest).encode("utf-8")),
                )
                manifests += 1

                if meeting.synced_at is None:
                    recording_dir = Path(meeting.recording_dir)
                    for filename in ("mic.wav", "speaker.wav", "mom.docx"):
                        local_path = recording_dir / filename
                        if local_path.exists():
                            client.fput_object(settings.minio_bucket, f"{prefix}/{filename}", str(local_path))
                            uploaded += 1
                    meeting.synced_at = datetime.now(timezone.utc)
            await session.commit()
        return {"manifests": manifests, "uploaded": uploaded}

    return asyncio.run(_run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/sync/test_minio_client.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/sync/minio_client.py tests/sync/test_minio_client.py
git commit -m "feat(sync): push locally-owned meetings to MinIO"
```

---

### Task 6: `pull()`

**Files:**
- Modify: `app/sync/minio_client.py`
- Modify: `tests/sync/test_minio_client.py`

**Interfaces:**
- Consumes: `repo.get_or_create_speaker` (existing)
- Produces: `pull(session_factory, settings) -> dict` (returns `{"pulled": int}`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/sync/test_minio_client.py`:

```python
def _fake_object(name):
    obj = MagicMock()
    obj.object_name = name
    return obj


def _fake_manifest_response(manifest: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(manifest).encode("utf-8")
    return resp


def test_pull_creates_local_meeting_from_remote_manifest(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)

    remote_manifest = {
        "title": "Rapat Remote", "scheduled_time": None, "start_time": None, "end_time": None,
        "status": "completed", "device_id": "dev2", "device_label": "Laptop Lain",
        "segments": [
            {"speaker_label": "Anda", "source": "mic", "start_ms": 0, "end_ms": 500, "text": "Halo"},
            {"speaker_label": "Speaker 1", "source": "speaker", "start_ms": 500, "end_ms": 900, "text": "Mari mulai"},
        ],
        "summary": {"mom_json": "{}", "has_docx": True, "groq_model": "m", "status": "ready"},
    }
    fake_client.list_objects.return_value = [_fake_object("dev2/uuid123/manifest.json")]
    fake_client.get_object.return_value = _fake_manifest_response(remote_manifest)

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 1

    async def _get():
        async with session_factory() as session:
            r = await session.execute(select(Meeting))
            return r.scalars().all()

    meetings = asyncio.run(_get())
    assert len(meetings) == 1
    assert meetings[0].title == "Rapat Remote"
    assert meetings[0].device_id == "dev2"
    assert meetings[0].recording_dir == str(tmp_path / "dev2" / "uuid123")

    async def _get_segments():
        async with session_factory() as session:
            r = await session.execute(select(TranscriptSegment))
            return r.scalars().all()

    segments = asyncio.run(_get_segments())
    assert len(segments) == 2
    assert {s.text for s in segments} == {"Halo", "Mari mulai"}

    async def _get_summary():
        async with session_factory() as session:
            return await repo.get_summary(session, meetings[0].id)

    summary = asyncio.run(_get_summary())
    assert summary.mom_json == "{}"
    assert summary.docx_path == str(tmp_path / "dev2" / "uuid123" / "mom.docx")


def test_pull_skips_manifests_owned_by_local_device(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    fake_client.list_objects.return_value = [_fake_object("dev1/uuid123/manifest.json")]

    session_factory = _make_db()
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 0
    fake_client.get_object.assert_not_called()


def test_pull_skips_manifests_already_known_locally(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    fake_client.list_objects.return_value = [_fake_object("dev2/uuid123/manifest.json")]

    session_factory = _make_db()

    async def _seed_existing():
        async with session_factory() as session:
            await repo.create_meeting(
                session, "Sudah Ada", None,
                recording_dir=str(tmp_path / "dev2" / "uuid123"), device_id="dev2",
            )
            await session.commit()

    asyncio.run(_seed_existing())
    settings = FakeSettings(device_id="dev1")
    settings.recordings_dir = tmp_path

    result = minio_client.pull(session_factory, settings)

    assert result["pulled"] == 0
    fake_client.get_object.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/sync/test_minio_client.py -v -k pull`
Expected: FAIL — `AttributeError: module 'app.sync.minio_client' has no attribute 'pull'`

- [ ] **Step 3: Write the implementation**

Add to `app/sync/minio_client.py`:

```python
def _parse_iso(value: str | None):
    return datetime.fromisoformat(value) if value else None


def pull(session_factory, settings) -> dict:
    import asyncio

    async def _run():
        client = _client(settings)
        pulled = 0
        async with session_factory() as session:
            for obj in client.list_objects(settings.minio_bucket, recursive=True):
                if not obj.object_name.endswith("/manifest.json"):
                    continue
                device_id, meeting_uuid, _ = obj.object_name.split("/", 2)
                if device_id == settings.device_id:
                    continue
                recording_dir = Path(settings.recordings_dir) / device_id / meeting_uuid
                existing = await session.execute(
                    select(Meeting).where(Meeting.recording_dir == str(recording_dir))
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                response = client.get_object(settings.minio_bucket, obj.object_name)
                manifest = json.loads(response.read())

                meeting = Meeting(
                    title=manifest["title"],
                    scheduled_time=_parse_iso(manifest.get("scheduled_time")),
                    start_time=_parse_iso(manifest.get("start_time")),
                    end_time=_parse_iso(manifest.get("end_time")),
                    status=manifest["status"], device_id=manifest["device_id"],
                    device_label=manifest.get("device_label"), recording_dir=str(recording_dir),
                )
                session.add(meeting)
                await session.flush()

                label_to_speaker_id: dict[str, int | None] = {"Anda": None}
                for seg in manifest["segments"]:
                    label = seg["speaker_label"]
                    if label not in label_to_speaker_id:
                        speaker = await repo.get_or_create_speaker(session, meeting.id, label)
                        label_to_speaker_id[label] = speaker.id
                    session.add(TranscriptSegment(
                        meeting_id=meeting.id, speaker_id=label_to_speaker_id[label],
                        source=seg["source"], start_ms=seg["start_ms"], end_ms=seg["end_ms"],
                        text=seg["text"], is_final=True,
                    ))

                if manifest.get("summary"):
                    s = manifest["summary"]
                    session.add(Summary(
                        meeting_id=meeting.id, mom_json=s["mom_json"],
                        docx_path=str(recording_dir / "mom.docx") if s.get("has_docx") else None,
                        groq_model=s.get("groq_model", ""), status=s.get("status", "ready"),
                    ))
                pulled += 1
            await session.commit()
        return {"pulled": pulled}

    return asyncio.run(_run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/sync/test_minio_client.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/sync/minio_client.py tests/sync/test_minio_client.py
git commit -m "feat(sync): pull other devices' manifests into the local database"
```

---

### Task 7: `download_file()` — on-demand fetch

**Files:**
- Modify: `app/sync/minio_client.py`
- Modify: `tests/sync/test_minio_client.py`

**Interfaces:**
- Produces: `download_file(settings, device_id: str, meeting_dir: str, filename: str, dest: Path) -> None`

- [ ] **Step 1: Write the failing test**

Append to `tests/sync/test_minio_client.py`:

```python
def test_download_file_fetches_object_to_dest(monkeypatch, tmp_path):
    fake_module = _fake_minio_module()
    fake_client = fake_module.Minio.return_value
    monkeypatch.setitem(sys.modules, "minio", fake_module)
    dest = tmp_path / "mom.docx"

    minio_client.download_file(FakeSettings(), "dev2", "uuid123", "mom.docx", dest)

    fake_client.fget_object.assert_called_once_with("meetings", "dev2/uuid123/mom.docx", str(dest))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/sync/test_minio_client.py -v -k download_file`
Expected: FAIL — `AttributeError: module 'app.sync.minio_client' has no attribute 'download_file'`

- [ ] **Step 3: Write the implementation**

Add to `app/sync/minio_client.py`:

```python
def download_file(settings, device_id: str, meeting_dir: str, filename: str, dest: Path) -> None:
    client = _client(settings)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.fget_object(settings.minio_bucket, f"{device_id}/{meeting_dir}/{filename}", str(dest))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/sync/test_minio_client.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/sync/minio_client.py tests/sync/test_minio_client.py
git commit -m "feat(sync): on-demand single-file download from MinIO"
```

---

### Task 8: "Sync Sekarang" button in Riwayat

**Files:**
- Modify: `app/ui/history_view.py`
- Modify: `app/ui/controller.py`
- Modify: `tests/ui/test_history_view.py`
- Modify: `tests/ui/test_controller.py`

**Interfaces:**
- Consumes: `app.sync.minio_client.{push, pull, is_configured}` (Tasks 4-6)
- Produces: `RecorderController.sync_now() -> dict` (returns `{"uploaded": int, "manifests": int, "pulled": int}`); `RecorderController.minio_configured -> bool`; `HistoryView` gains a "Sync Sekarang" button

- [ ] **Step 1: Write the failing tests**

In `tests/ui/test_controller.py`, add near the other controller tests:

```python
def test_sync_now_calls_push_then_pull(tmp_path, monkeypatch):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    calls = []
    monkeypatch.setattr(
        "app.ui.controller.minio_client.push",
        lambda sf, settings: calls.append("push") or {"manifests": 1, "uploaded": 2},
    )
    monkeypatch.setattr(
        "app.ui.controller.minio_client.pull",
        lambda sf, settings: calls.append("pull") or {"pulled": 3},
    )
    controller = _make_controller(tmp_path, session_factory)
    controller._settings = SimpleNamespace(minio_is_configured=True)

    result = controller.sync_now()

    assert calls == ["push", "pull"]
    assert result == {"manifests": 1, "uploaded": 2, "pulled": 3}
```

Modify `_make_controller` in `tests/ui/test_controller.py` to also accept
and forward a `settings` param (default `None`):

```python
def _make_controller(tmp_path, session_factory, transcribe_fn=_noop_transcribe_fn,
                      summarize_fn=_noop_summarize_fn, recorder_cls=FakeRecorder,
                      live_session_factory=None, device_id=None, device_label=None,
                      settings=None):
    return RecorderController(
        session_factory=session_factory,
        recorder_factory=lambda mic, speaker: recorder_cls(mic, speaker),
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=tmp_path,
        live_session_factory=live_session_factory,
        device_id=device_id,
        device_label=device_label,
        settings=settings,
    )
```

In `tests/ui/test_history_view.py`, extend `FakeController`:

```python
    def __init__(self, meetings):
        self._meetings = meetings
        ...  # existing fields unchanged
        self.minio_configured = False
        self.sync_calls = 0
        self.sync_result = {"manifests": 0, "uploaded": 0, "pulled": 0}

    def sync_now(self):
        self.sync_calls += 1
        return self.sync_result
```

Add new tests:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_sync_button_hidden_when_minio_not_configured():
    root = tk.Tk()
    controller = FakeController([])
    controller.minio_configured = False
    view = HistoryView(root, controller)

    assert str(view._sync_button.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_sync_button_shown_and_calls_controller_when_configured():
    root = tk.Tk()
    controller = FakeController([])
    controller.minio_configured = True
    controller.sync_result = {"manifests": 2, "uploaded": 1, "pulled": 3}
    view = HistoryView(root, controller)
    assert str(view._sync_button.winfo_manager()) == "pack"

    refreshes_before = controller.list_meetings_calls
    root.after(10, view._handle_sync)
    _pump_until(root, lambda: controller.list_meetings_calls > refreshes_before)

    assert controller.sync_calls == 1
    assert "3" in view._status_label.cget("text")  # pulled count surfaced
    root.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_controller.py tests/ui/test_history_view.py -v -k sync`
Expected: FAIL — `RecorderController` has no `sync_now`, `HistoryView` has
no `_sync_button`.

- [ ] **Step 3: Write the implementation**

In `app/ui/controller.py`, add the import at the top:

```python
from app.sync import minio_client
```

Add `settings=None` to `RecorderController.__init__`'s signature and body
(next to the `device_id`/`device_label` params added by the device
identity plan):

```python
        device_id: str | None = None,
        device_label: str | None = None,
        settings=None,
    ):
        ...
        self._device_id = device_id
        self._device_label = device_label
        self._settings = settings
```

Add a new method:

```python
    @property
    def minio_configured(self) -> bool:
        return self._settings is not None and self._settings.minio_is_configured

    def sync_now(self) -> dict:
        """Blocking -- call from a background thread."""
        push_result = minio_client.push(self._session_factory, self._settings)
        pull_result = minio_client.pull(self._session_factory, self._settings)
        return {**push_result, **pull_result}
```

In `app/main.py`, pass `settings=settings` into the existing
`RecorderController(...)` construction (alongside `device_id`/
`device_label` from the device identity plan):

```python
        device_id=settings.device_id,
        device_label=settings.device_label,
        settings=settings,
    )
```

In `app/ui/history_view.py`, add the button next to `self._delete_button`
in `__init__`:

```python
        self._sync_button = tk.Button(action_frame, text="Sync Sekarang", command=self._handle_sync)
```

Add a handler (this is a global action, not per-meeting, so it doesn't use
the existing `_start_action`/`_run_in_background` helpers, which are keyed
to a `meeting_id`):

```python
    def _handle_sync(self) -> None:
        if self._sync_in_progress:
            return
        self._sync_in_progress = True
        self._sync_button.config(state="disabled")

        def _worker():
            try:
                result = self._controller.sync_now()
                message = (
                    f"Sync selesai: {result['manifests']} meeting diunggah, "
                    f"{result['uploaded']} file diunggah, {result['pulled']} meeting ditarik."
                )
            except Exception as exc:
                logger.warning("sync failed: %s", exc)
                message = f"Sync gagal: {exc}"
            finally:
                self._sync_in_progress = False
                self.after(0, lambda: self._status_label.config(text=message))
                self.after(0, self.refresh)

        threading.Thread(target=_worker, daemon=True).start()
```

Add `self._sync_in_progress = False` to `HistoryView.__init__` (next to
the other instance state near the top, e.g. next to `self._busy_meeting_ids`).

In `_update_action_panel` (or wherever the panel is first built —
`__init__` calls `self.refresh()` which calls `_update_action_panel()`),
show/hide the sync button based on `self._controller.minio_configured`.
Add this at the START of `_update_action_panel`, before the per-meeting
button logic:

```python
        if self._controller.minio_configured:
            self._sync_button.pack(side="right")
        else:
            self._sync_button.pack_forget()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_controller.py tests/ui/test_history_view.py -v`
Expected: all passed

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ui/controller.py app/ui/history_view.py app/main.py tests/ui/test_controller.py tests/ui/test_history_view.py
git commit -m "feat(ui): add Sync Sekarang button to Riwayat"
```

---

### Task 9: Read-only action panel for pulled meetings + on-demand docx download

**Files:**
- Modify: `app/ui/history_view.py`
- Modify: `app/ui/controller.py`
- Modify: `tests/ui/test_history_view.py`
- Modify: `tests/ui/test_controller.py`

**Interfaces:**
- Consumes: `app.sync.minio_client.download_file` (Task 7)
- Produces: `RecorderController.ensure_docx_available(meeting_id) -> str | None`
- Note (scope boundary, per spec §2/§10): this task hides
  Transkrip/Ringkasan/Coba Lagi in the UI for meetings not owned by this
  device. It does NOT add a server-side/controller-level guard preventing
  `run_transcribe`/`run_summarize`/`retry` from being called directly on a
  foreign meeting_id — the spec scopes this as a UI affordance, not an
  access-control boundary, since there is no multi-user auth model in this
  single-process desktop app to enforce against.

- [ ] **Step 1: Write the failing tests**

In `tests/ui/test_history_view.py`, update the `_meeting()` helper (already
carrying `device_label` from the device identity plan) to also accept
`device_id`:

```python
def _meeting(id, title, status, error_message=None, failed_stage=None,
             device_label=None, device_id=None):
    return SimpleNamespace(
        id=id, title=title, status=status,
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        error_message=error_message, failed_stage=failed_stage,
        device_label=device_label, device_id=device_id,
    )
```

Give `FakeController` a `local_device_id` attribute:

```python
        self.minio_configured = False
        self.sync_calls = 0
        self.sync_result = {"manifests": 0, "uploaded": 0, "pulled": 0}
        self.local_device_id = "dev1"
```

Add new tests:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_own_meeting_shows_processing_buttons():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded", device_id="dev1")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    assert str(view._transcribe_button.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_pulled_meeting_hides_processing_buttons_but_keeps_view_and_delete():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat Lain", "recorded", device_id="dev2")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    assert str(view._transcribe_button.winfo_manager()) == ""
    assert str(view._delete_button.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_pulled_meeting_transcribed_status_shows_only_view_not_summarize():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat Lain", "transcribed", device_id="dev2")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    assert str(view._summarize_button.winfo_manager()) == ""
    assert str(view._view_transcript_button.winfo_manager()) == "pack"
    root.destroy()
```

In `tests/ui/test_controller.py`, add:

```python
def test_ensure_docx_available_returns_local_path_unchanged_for_own_meeting(tmp_path):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory, device_id="dev1")

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat", None, recording_dir=str(tmp_path), device_id="dev1",
            )
            await repo.save_summary(
                session, meeting.id, mom_json="{}", docx_path=str(tmp_path / "mom.docx"),
                groq_model="m", status="ready",
            )
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())
    (tmp_path / "mom.docx").write_bytes(b"fake docx")

    path = controller.ensure_docx_available(meeting_id)

    assert path == str(tmp_path / "mom.docx")


def test_ensure_docx_available_downloads_missing_file_for_pulled_meeting(tmp_path, monkeypatch):
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)
    controller = _make_controller(tmp_path, session_factory, device_id="dev1")
    controller._settings = SimpleNamespace()
    download_calls = []
    monkeypatch.setattr(
        "app.ui.controller.minio_client.download_file",
        lambda settings, device_id, meeting_dir, filename, dest: download_calls.append(
            (device_id, meeting_dir, filename, dest)
        ),
    )
    docx_path = tmp_path / "dev2" / "uuid123" / "mom.docx"

    async def _seed():
        async with session_factory() as session:
            meeting = await repo.create_meeting(
                session, "Rapat Lain", None, recording_dir=str(tmp_path / "dev2" / "uuid123"),
                device_id="dev2",
            )
            await repo.save_summary(
                session, meeting.id, mom_json="{}", docx_path=str(docx_path),
                groq_model="m", status="ready",
            )
            await session.commit()
            return meeting.id

    meeting_id = asyncio.run(_seed())
    # docx_path deliberately not created on disk -- must trigger a download

    path = controller.ensure_docx_available(meeting_id)

    assert path == str(docx_path)
    assert download_calls == [("dev2", "uuid123", "mom.docx", docx_path)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ui/test_history_view.py tests/ui/test_controller.py -v -k "pulled or own_meeting or ensure_docx"`
Expected: FAIL — `_update_action_panel` doesn't check `device_id` yet;
`RecorderController` has no `ensure_docx_available`.

- [ ] **Step 3: Write the implementation**

By the time this task runs, `_update_action_panel` already has: the
delete-button pack/forget logic (shipped earlier, independent of these
plans) in its existing `for button in (...)` reset loop and its trailing
`if status != "recording":` block; AND, from Task 8 of this same plan, a
sync-button show/hide block at the very start. Only the middle
status-branch block changes here — the delete-button logic at the end is
untouched by this edit (don't include it in the search/replace; leaving it
out of the matched span is what keeps it as-is).

Replace the existing status-branch block:

```python
        state = "disabled" if meeting.id in self._busy_meeting_ids else "normal"
        if status == "recorded":
            self._transcribe_button.config(state=state)
            self._transcribe_button.pack(side="left")
        elif status == "transcribed":
            self._summarize_button.config(state=state)
            self._summarize_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "completed":
            self._download_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "failed":
            self._retry_button.config(state=state)
            self._retry_button.pack(side="left")
```

with:

```python
        state = "disabled" if meeting.id in self._busy_meeting_ids else "normal"
        is_own = meeting.device_id is None or meeting.device_id == self._controller.local_device_id
        if status == "recorded" and is_own:
            self._transcribe_button.config(state=state)
            self._transcribe_button.pack(side="left")
        elif status == "transcribed":
            if is_own:
                self._summarize_button.config(state=state)
                self._summarize_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "completed":
            self._download_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "failed" and is_own:
            self._retry_button.config(state=state)
            self._retry_button.pack(side="left")
```

(`meeting.device_id is None` covers meetings created before the device
identity plan shipped, or in dev mode where `device_id` defaults to empty
— treated as "own" so existing behavior for pre-existing rows is
unaffected. The trailing `if status != "recording": self._delete_button...`
block that already exists after this — Delete stays available regardless
— is left completely alone by this edit.)

In `app/ui/controller.py`, add the import at the top (if not already
present from Task 8):

```python
from app.sync import minio_client
```

Add a `local_device_id` property and `ensure_docx_available`:

```python
    @property
    def local_device_id(self) -> str | None:
        return self._device_id

    def ensure_docx_available(self, meeting_id: int) -> str | None:
        """Blocking -- call from a background thread. Downloads the docx from
        MinIO on demand if this meeting was pulled from another device and
        the file isn't on disk locally yet."""
        async def _get():
            async with self._session_factory() as session:
                meeting = await session.get(Meeting, meeting_id)
                summary = await repo.get_summary(session, meeting_id)
                return meeting, summary

        meeting, summary = asyncio.run(_get())
        if summary is None or summary.docx_path is None:
            return None
        docx_path = Path(summary.docx_path)
        if docx_path.exists():
            return str(docx_path)
        if meeting.device_id and meeting.device_id != self._device_id:
            meeting_dir_name = Path(meeting.recording_dir).name
            minio_client.download_file(
                self._settings, meeting.device_id, meeting_dir_name, "mom.docx", docx_path,
            )
            return str(docx_path)
        return None
```

Add `from app.storage.models import Meeting` to `app/ui/controller.py`'s
imports if it isn't already there (check first — `Meeting` is already
imported for `run_transcribe`).

In `app/ui/history_view.py::_handle_download`, replace the direct
`get_docx_path` call with the new download-aware path, run through the
existing per-meeting background-action machinery so a network fetch
doesn't block the UI thread:

```python
    def _handle_download(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        self._start_action(self._download_button, self._download_and_open)

    def _download_and_open(self, meeting_id: int) -> None:
        docx_path = self._controller.ensure_docx_available(meeting_id)
        if docx_path:
            self.after(0, lambda: os.startfile(docx_path))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ui/test_history_view.py tests/ui/test_controller.py -v`
Expected: all passed

Note: the existing `test_download_button_calls_controller_get_docx_path`
test (from before this plan) calls `_handle_download` and expects
`os.startfile` to be invoked synchronously with the result of
`get_docx_path`. That test now exercises a background thread instead —
update it to match the new async flow:

```python
@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_download_button_calls_controller_get_docx_path(monkeypatch):
    root = tk.Tk()
    opened = []
    monkeypatch.setattr("app.ui.history_view.os.startfile", lambda path: opened.append(path))
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    controller.local_device_id = "dev1"
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    refreshes_before = controller.list_meetings_calls
    root.after(10, view._handle_download)
    _pump_until(root, lambda: controller.list_meetings_calls > refreshes_before)

    assert opened == ["C:/recordings/1/mom.docx"]
    root.destroy()
```

This also requires `FakeController.get_docx_path` to keep working as
`ensure_docx_available`'s stand-in for this specific test — add an
`ensure_docx_available` method to `FakeController` in
`tests/ui/test_history_view.py` alongside the existing `get_docx_path`:

```python
    def ensure_docx_available(self, meeting_id):
        self.download_calls.append(meeting_id)
        return "C:/recordings/1/mom.docx"
```

Run: `pytest tests/ui/test_history_view.py -v`
Expected: all passed, including the updated download test.

Run: `pytest -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add app/ui/history_view.py app/ui/controller.py tests/ui/test_history_view.py tests/ui/test_controller.py
git commit -m "feat(ui): read-only actions for pulled meetings, on-demand docx download"
```

---

### Task 10: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass — baseline from before this plan (including the
storage-backend, device-identity, and hardware-capability plans' tests),
plus every test added in Tasks 1-9.

- [ ] **Step 2: Manually verify zero network activity when MinIO is unconfigured**

With `.env`/config.json left without any `MINIO_*` values (the default),
confirm the "Sync Sekarang" button never appears in Riwayat. This is the
concrete check for the spec's "default off = zero network activity"
principle — not something the automated test suite alone proves for a
real running app.

- [ ] **Step 3: Commit (if Step 1 or 2 required any fixes)**

```bash
git add -A
git commit -m "fix: address regressions found in full verification pass"
```

(Skip this commit entirely if no changes were needed.)
