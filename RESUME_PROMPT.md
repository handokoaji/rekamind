# Resume Prompt — Rekamind Multi-Device Feature Work

Copy-paste the prompt at the bottom of this file into a new Claude Code
session to continue exactly where this one left off.

## Branding (decided this session)

The project is rebranded **Rekamind** (from "rekam" + "remind" — a
bilingual pun, not a plain suffix name). Tagline: "Record it. Remember it.
Keep it yours." License: **MIT** (`LICENSE` file added, copyright
`handokoaji` 2026). `pyproject.toml`'s `name` is now `"rekamind"`. Every
user-facing string (window title, setup wizard title, tray icon/tooltip,
error dialog titles) was renamed from "Meeting Recorder" to "Rekamind" —
see commit `480bc56`. A `README.md` with the full positioning/feature
list/quickstart was added at the worktree root, and `CLAUDE.md` was
updated to document the storage-backend/device-identity/MinIO-sync
architecture that Plans 1-4 added (it previously only described the
pre-multi-device architecture). Names considered and rejected along the way
(collisions found): Notula, Wicara, Parley, Rekap — see conversation
history if picking a *different* name is ever revisited.

**Do not rename anything else without checking with the human partner
first** — the rebrand was scoped to user-facing strings + packaging
metadata only. Internal Python identifiers (the `app` package, module
names, `RecorderController`, etc.) were deliberately left alone.

## State as of 2026-07-31

**Worktree:** `C:\Project\meeting\.claude\worktrees\storage-backend-wizard`
**Branch:** `worktree-storage-backend-wizard` (pushed to `origin`, tracking
`origin/worktree-storage-backend-wizard`)
**Latest commit:** `480bc56` (rebrand) on top of `7e39db7` (Plan #4 complete)

**Merge-to-master status: explicitly deferred, not a bug.** The human
partner asked about merging to master mid-session; when shown the open
items below (Plan #5 not started, no final whole-branch review, the known
Tk-threading crash risk, MinIO never tested against a real server) they
chose "tunggu, selesaikan dulu" (wait, finish first) over merging as-is.
**Do not merge this branch to master until Plan #5 is done and a final
whole-branch review has happened**, unless the human partner explicitly
says otherwise in a future session. When it is time to merge: **direct
`git merge`, not a GitLab merge request** — the human partner said so
explicitly (the repo is hosted at
`https://git.dev.ugm.ac.id/aksi_riset/meeting`, which offers an MR flow on
push; skip it).

This worktree/branch was created via the `EnterWorktree` tool from a session
using `superpowers:subagent-driven-development`. If the worktree directory
no longer exists but the branch does (`git branch --list
worktree-storage-backend-wizard` from the main checkout, or `git fetch
origin` then `git branch --list -r` if even the local branch is gone),
recreate the worktree with `git worktree add
.claude/worktrees/storage-backend-wizard worktree-storage-backend-wizard`
(or `EnterWorktree` with `path:` pointing at it, if the tool supports
re-registering an existing branch — otherwise a fresh `EnterWorktree name:`
and `git checkout worktree-storage-backend-wizard` inside it works too).
**Do not delete this branch.**

The shared venv at `C:\Project\meeting\.venv` has all dependencies
installed (including `minio`, added mid-session). No per-worktree venv is
needed — running `C:\Project\meeting\.venv\Scripts\python.exe` from
*within* the worktree directory correctly resolves the worktree's own
`app`/`tests` packages (verified empirically this session).

## What's done (5 design specs, 4 of 5 implementation plans fully executed)

All specs live in `docs/superpowers/specs/2026-07-31-*.md`, all plans in
`docs/superpowers/plans/2026-07-31-*.md` (present in this worktree and
already on `master` too, since spec/plan docs were committed to master
directly before implementation began).

| # | Plan | Status |
|---|------|--------|
| 1 | `2026-07-31-storage-backend-setup-wizard.md` | ✅ 8/8 tasks done |
| 2 | `2026-07-31-device-identity.md` | ✅ 8/8 tasks done (+ the small "durasi meeting" item, folded into its Task 7) |
| 3 | `2026-07-31-hardware-capability-check.md` | ✅ 3/3 tasks done |
| 4 | `2026-07-31-minio-file-sync.md` | ✅ 10/10 tasks done |
| 5 | `2026-07-31-exe-packaging.md` | ❌ **NOT STARTED — this is the next work** |

Every task across plans 1-4 was implemented directly by the controller
(no subagent dispatch) after the session hit its monthly spend limit
partway through Plan 1 — the human partner explicitly chose "kerjakan
langsung tanpa subagent" over stopping or retrying subagents. TDD was still
followed rigorously for every task (RED test written and confirmed failing,
then GREEN implementation, then full-suite regression check, then commit).

SDD ledgers with full task-by-task notes (self-caught bugs, deviations,
etc.) are at `.superpowers/sdd/<plan-basename>/progress.md` inside the
worktree — **these are git-ignored**, so they only exist if the worktree
directory itself still exists. If it's gone, the full history is still in
the git commit messages (each commit message documents what it did and why
in detail) — read `git log --stat` on the branch.

Full test suite: **243 passed**, 2 skipped (pre-existing Tcl/Tk env flake,
harmless), 2 deselected (`hardware`/`postgres` markers, excluded by
`pytest.ini` default). Verified clean across 4 consecutive runs.

## Two things found and fixed along the way (worth knowing about)

1. **Security fix (Plan 4, Task 7):** an automated post-commit security
   review caught a path-traversal vulnerability in `app/sync/minio_client.py`'s
   `pull()` — it built local filesystem paths directly from untrusted MinIO
   object names (another device's data, potentially malicious/compromised).
   Fixed in commit `a0aded5` with charset validation + resolved-path
   containment checks. Already covered by tests.

2. **Pre-existing Tk/threading crash risk (Plan 4, Task 9) — NOT fully
   fixed, flagged for follow-up:** `app/ui/history_view.py`'s
   `_run_in_background()` (used by Transkrip/Ringkasan/Coba Lagi/Hapus,
   predating all this session's work) has a real bug where its background
   thread's `self.after(...)` calls race against Tk teardown, causing a
   **hard process crash** (`Windows fatal exception 0x80000003`, not just a
   Python exception) under full-suite load. Measured ~66% reproduction rate
   when the new on-demand-download feature was ALSO routed through this
   same pattern per the original plan text. Worked around for the new
   Task 9 code by keeping `_handle_download` synchronous instead (see
   commit `7e39db7`'s message for full reasoning) — this avoids adding a
   new trigger site, but **does not fix the underlying bug for the
   already-existing Transkrip/Ringkasan/Coba Lagi/Hapus buttons**, which
   still carry this crash risk. Recommend a dedicated hardening task before
   treating `pytest -q` as an unconditionally reliable gate long-term —
   likely fix direction: replace direct `self.after()` calls from
   background threads with a thread-safe queue drained only from the main
   loop (the pattern `app/ui/window.py`'s `push_live_event`/
   `_drain_live_events` already uses correctly).

## Manual/real-world verification still outstanding (cannot be done by an agent)

- Plan 3 (hardware capability): the `openvino` backend-detection logic was
  never verified on real Intel Ultra 7 155H hardware — only unit-tested
  under mocks. See plan §5 / the design spec for what "verified" means here.
- Plan 1 (storage backend): dev-mode-unchanged was verified via a
  non-interactive smoke check (see ledger), not by literally launching the
  GUI and clicking through it.
- Plan 4 (MinIO sync): the full push→pull round trip has only been tested
  against a mocked `Minio` client (`sys.modules["minio"]` substitution) —
  never against a real MinIO server. Worth a manual pass with two real
  device installs pointed at the same bucket before shipping this feature.

## What's next: Plan 5 (packaging)

Read `docs/superpowers/plans/2026-07-31-exe-packaging.md` in full before
starting. 6 tasks:

1. App version constant (`app/__init__.py::__version__`) + bundled-ffmpeg
   PATH detection in `app/main.py`
2. `app/update_check.py` — stdlib-only (`urllib.request`, no new
   dependency) update-availability check against a Releases API
3. Wire the update check into startup + a non-blocking UI notification
4. PyInstaller build configuration (`packaging/MeetingRecorder.spec` +
   `packaging/README.md`)
5. Inno Setup installer script (`packaging/installer.iss`)
6. Full regression pass + a manual distribution checklist (install on a
   clean machine, confirm it runs without Python/venv present, etc.)

Tasks 1-3 are normal application code — TDD them the same way every task in
plans 1-4 was done (see any commit in this branch for the exact
established rhythm: write failing test → confirm RED → implement → confirm
GREEN → run full suite → commit with a message explaining what and why).

Tasks 4-5 are NOT Python code and have no pytest coverage by design (per
the plan's own Testing section) — they end in "run this command, check
this output" manual verification steps instead of a red/green cycle.
Task 6 is verification-only.

**Continue in the SAME worktree/branch** (`worktree-storage-backend-wizard`)
— don't start a fresh worktree for Plan 5, since it doesn't depend on
anything from Plans 1-4 code-wise per the plan's own Global Constraints,
but keeping one branch for the whole "multi-device distribution" feature
set makes the eventual merge to `master` simpler (one PR/branch, not five).

After Plan 5 is done, the whole branch needs a final review pass and a
decision on how to merge into `master` (which will have diverged further
by then — `master` already gained unrelated Groq-chunking commits while
this branch was in progress; that's a clean, non-overlapping merge, not a
conflict, but check again before merging since more time will have
passed). Use `superpowers:finishing-a-development-branch` for that step
once Plan 5 is done and reviewed.

---

## Prompt to paste into the new session

```
Lanjutkan pekerjaan multi-device/storage feature (Rekamind) dari sesi
sebelumnya. Baca file RESUME_PROMPT.md di root repo
(C:\Project\meeting\RESUME_PROMPT.md) untuk konteks lengkap -- termasuk
rebranding ke "Rekamind" + lisensi MIT yang sudah selesai, dan status
merge-to-master yang SENGAJA ditunda (jangan merge tanpa konfirmasi ulang).
Lanjutkan ke Plan #5 (packaging .exe) --
docs/superpowers/plans/2026-07-31-exe-packaging.md -- di worktree/branch
yang sama (worktree-storage-backend-wizard, sudah di-push ke origin).
Kerjakan langsung (tanpa subagent) mengikuti ritme TDD yang sudah dipakai
di semua commit sebelumnya di branch ini: tulis test gagal dulu, konfirmasi
RED, implementasi, konfirmasi GREEN, jalankan full suite, baru commit dan
push ke origin.
```
