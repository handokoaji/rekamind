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

## State as of 2026-08-01

**Worktree:** `C:\Project\meeting\.claude\worktrees\storage-backend-wizard`
**Branch:** `worktree-storage-backend-wizard` (pushed to `origin`, tracking
`origin/worktree-storage-backend-wizard`)
**Latest commit:** `465edd7` (Plan #5 complete) on top of `480bc56` (rebrand)

**Plan #5 (packaging) is now done — see its own section below.** The one
remaining gate before merge is the **final whole-branch review** (never
done yet across all 5 plans) plus the manual/real-world verification items
listed further down (none of which an agent can do).

**Merge-to-master status: still explicitly deferred, not a bug.** The human
partner asked about merging to master earlier in this feature's work; when
shown the open items (Plan #5 not started at the time, no final
whole-branch review, the known Tk-threading crash risk, MinIO never tested
against a real server) they chose "tunggu, selesaikan dulu" (wait, finish
first) over merging as-is. **Do not merge this branch to master until a
final whole-branch review has happened**, unless the human partner
explicitly says otherwise in a future session. When it is time to merge:
**direct `git merge`, not a GitLab merge request** — the human partner said
so explicitly (the repo is hosted at
`https://git.dev.ugm.ac.id/aksi_riset/meeting`, which offers an MR flow on
push; skip it). Use `superpowers:finishing-a-development-branch` for that
step.

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

## What's done (5 design specs, all 5 implementation plans fully executed)

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
| 5 | `2026-07-31-exe-packaging.md` | ✅ 6/6 tasks done (2026-08-01) |

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

Full test suite: **257 passed**, 2 skipped (pre-existing Tcl/Tk env flake,
harmless), 2 deselected (`hardware`/`postgres` markers, excluded by
`pytest.ini` default). Verified clean across multiple consecutive runs on
2026-08-01 (Plan #4's known intermittent Tk-teardown access-violation crash
— see below — reproduced twice during these runs and is unrelated to
Plan #5's changes, all of which are either pure-stdlib or Tk-widget-additive).

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

## Plan #5 (packaging) — what was actually built (2026-08-01)

All 6 tasks done, TDD throughout (RED confirmed → GREEN → full suite →
commit), same rhythm as plans 1-4:

1. `app/__init__.py::__version__ = "0.1.0"` (kept in sync with
   `pyproject.toml` manually — two independent version strings by design,
   see the file's own comment) + `app/main.py::prepend_bundled_ffmpeg_to_path()`,
   called as the very first line of `main()`. Commit `a3d7d1f`.
2. `app/update_check.py::check_for_update()` — stdlib `urllib.request` only,
   silent on any failure (blank URL, network error, malformed JSON), handles
   both GitHub (dict) and GitLab (list) Releases API response shapes.
   `RELEASES_API_URL`/`RELEASES_PAGE_URL` are blank on purpose (zero network
   activity until a maintainer fills them in once a real release exists —
   see Task 6 note below). Commit `094956f`.
3. `app/main.py::_start_update_check()` (background thread, calls the
   on-startup callback only if a newer version exists) wired into `main()`
   right after `window_ref["window"] = window`; `app/ui/window.py` gained
   `update_notice_var`/`update_notice_label` (clickable, opens
   `RELEASES_PAGE_URL` via `webbrowser.open`, no-op if blank) and an
   `"update_available"` branch in `_drain_live_events`. Commit `9873fdf`.
4. `packaging/MeetingRecorder.spec` (PyInstaller, `collect_all` for the
   heavy ML deps, `console=False`) + `packaging/README.md` (build steps).
   `.gitignore` gained `dist/`, `build/`, `packaging/ffmpeg/`,
   `packaging/Output/`. Commit `70b6167`.
5. `packaging/installer.iss` (Inno Setup — installs to `{autopf}`, Start
   Menu shortcuts, uninstaller; `AppVersion`/`OutputBaseFilename` need
   bumping by hand alongside `__version__` and `pyproject.toml` per
   release). Commit `465edd7`.
6. Full suite verified clean (257 passed) across multiple runs — see test
   count note above. The manual distribution checklist (install on a clean
   machine, etc.) is **not done** — cannot be done by an agent, see below.

**One addition beyond the plan's own text, done at the human partner's
request mid-session:** `check_ffmpeg_available()` in `app/main.py` now also
shows a `messagebox.showwarning` dialog with install steps
(`winget install ffmpeg`) when ffmpeg is missing, not just a stderr print —
a packaged `.exe` has no console window (`console=False` in the spec), so
the stderr warning alone would never reach a real user. Commit
`0f1d84e`, between Task 2 and Task 3 in the git log.

Tasks 4-5's own build/run/install verification (PyInstaller not installed
in this venv; building requires downloading a real `ffmpeg.exe`, running a
multi-minute build with heavy ML deps, then Inno Setup, then installing on
a clean machine) was **not attempted** — this matches the plan's own
Testing section, which describes these as manual steps for a human, not a
red/green cycle.

## What's next: final review + merge decision

Plan #5 is the last of the 5 implementation plans — there is no more
planned application code left in this feature series. What's left:

1. **A final whole-branch review** (never done across all 5 plans) — diff
   the whole branch against wherever `master` is by then, using whatever
   review process the human partner prefers (`code-review` skill, manual
   read-through, etc.).
2. **The manual/real-world verification items** listed above and in the
   "Manual/real-world verification still outstanding" section further up —
   none of these can be done by an agent.
3. Once both of those are satisfactorily addressed, use
   `superpowers:finishing-a-development-branch` to decide how to merge into
   `master` (which will have diverged further by then — check again before
   merging, `master` already had unrelated commits land while this branch
   was in progress last time this was checked). **Direct `git merge`, not a
   GitLab MR**, per the human partner's explicit instruction above.

---

## Prompt to paste into the new session

```
Lanjutkan pekerjaan multi-device/storage feature (Rekamind) dari sesi
sebelumnya. Baca file RESUME_PROMPT.md di root repo
(C:\Project\meeting\RESUME_PROMPT.md) untuk konteks lengkap -- termasuk
rebranding ke "Rekamind" + lisensi MIT, Plan #5 (packaging .exe) yang sudah
selesai (6/6 task), dan status merge-to-master yang SENGAJA ditunda (jangan
merge tanpa konfirmasi ulang).

Semua 5 plan implementasi sudah selesai. Yang tersisa: (1) final
whole-branch review yang belum pernah dilakukan di seluruh branch ini, (2)
item verifikasi manual yang tidak bisa dikerjakan agent (lihat bagian
"Manual/real-world verification still outstanding" di RESUME_PROMPT.md),
(3) baru setelah itu putuskan cara merge ke master pakai
superpowers:finishing-a-development-branch -- direct git merge, BUKAN
GitLab merge request.

Worktree/branch: worktree-storage-backend-wizard (sudah di-push ke
origin). Kerjakan langsung (tanpa subagent) kecuali diminta lain.
```
