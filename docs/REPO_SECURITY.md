🌐 **English + Bahasa Indonesia**

# Repository security / Keamanan repositori

Rekamind runs code on users' machines (installer, engine downloads, `pip` into the engine pack), so the repository is
treated as a supply chain. This page records what is enforced **in the repo** and what must be switched on **in GitHub
settings** (the latter cannot be committed).

*Rekamind menjalankan kode di komputer pengguna, jadi repositori diperlakukan sebagai rantai pasok. Halaman ini mencatat
apa yang diterapkan **di repo** dan apa yang harus diaktifkan **di pengaturan GitHub**.*

## Policy / Kebijakan

- The owner (`@handokoaji`) may push freely. **Everyone else changes the code only through a pull request that the owner
  reviews and approves**, with the checks passing.
- *Pemilik bebas mendorong langsung. **Orang lain hanya lewat pull request** yang ditinjau dan disetujui pemilik, dengan
  pemeriksaan CI lulus.*

## In the repo / Di dalam repo

| Control | Where |
|---|---|
| Review ownership of CI, scripts, engine download and auth code | `.github/CODEOWNERS` |
| Dependency updates arrive as reviewable PRs | `.github/dependabot.yml` |
| Third-party Actions pinned to a full commit SHA (not a movable tag) | `.github/workflows/*.yml` |
| Default `GITHUB_TOKEN` is read-only; only `publish` jobs get `contents: write`, only the image job gets `packages: write` | `permissions:` in each workflow |
| Checkouts do not leave the token in `.git/config` (`persist-credentials: false`) | `.github/workflows/*.yml` |
| Release and engine-asset publishing run in the `release` environment, so a required reviewer can gate them | `environment: release` |
| No `pull_request_target`; fork PRs get no secrets | workflow triggers |
| Engine packages install with `--only-binary=:all:` (no `setup.py` from source packages) and only from `pypi.org`, `files.pythonhosted.org`, `download.pytorch.org` | `server/rekamind_server/enginepack.py` |
| The native engine zip (`whisper-cli`) is checked against a **SHA-256 pinned in the app source** (`engine_pins.py`), not one published next to the file; size is pinned too; it is unpacked with a path check; download hosts are allow-listed. A replaced release is refused. | `server/rekamind_server/engine_pins.py`, `engine_assets.py` |
| Lockfiles for npm and Cargo are committed and CI installs from them (`npm ci`) | `web/`, `desktop/`, `recorder/` |

## In GitHub settings (do these once) / Di pengaturan GitHub (sekali saja)

1. **Ruleset for `master`** (Settings → Rules → Rulesets → New branch ruleset, target `master`):
   - Require a pull request before merging, **1 approval**, **require review from Code Owners**, dismiss stale approvals
     when new commits are pushed.
   - Require status checks to pass (the `v2 CI` jobs), require the branch to be up to date.
   - Block force pushes and deletions. Require linear history (optional).
   - **Bypass list: your own account / the "Repository admin" role only.** This is what lets the owner push freely
     while everyone else must go through a reviewed PR.
2. **Ruleset for tags `v*`**: restrict creation, update and deletion to the owner. A pushed `v*` tag triggers a release,
   so tag creation is a publishing right.
3. **Collaborators**: give people *Read* or *Triage*, not *Write*. Contributors use forks and pull requests.
4. **Actions → General**: workflow permissions = *Read repository contents*; "Require approval for all outside
   collaborators" for fork pull-request workflows; allow only actions from GitHub and the verified creators already
   used.
5. **Environments → `release`**: add yourself as a *Required reviewer* so publishing a release or the engine assets needs
   an explicit click.
6. **Code security**: enable Dependabot alerts and security updates, **secret scanning with push protection**, and
   **private vulnerability reporting** (it is what `SECURITY.md` points to). Optionally enable CodeQL.
7. **Your account**: two-factor authentication with a passkey or hardware key; consider SSH commit signing and the
   "Require signed commits" rule. A stolen owner session defeats every other control.

## Known gaps, not fixed yet / Celah yang belum ditutup

- **Engine download: pinned, but only for the Vulkan `whisper-cli`.** Its hash is in the app (closed). The CPU, NVIDIA and
  Intel engines are installed with `pip` from PyPI and are **not** covered by that pin (see the next item). Apps up to
  v0.4.0-beta.4 still trust the `manifest.json` of the `engine-assets` release, so never modify or delete that release.
  A signed manifest (Ed25519, key kept offline) would allow engine updates without an app release.
- **Python packages are not hash-pinned.** The engine pack and the frozen backend install `>=` ranges from PyPI at install
  or build time. A malicious new release of a dependency would be picked up. Better: a lock file with hashes
  (`--require-hashes`) per engine kind and for the build.
- **Models load pickled weights** (PyTorch `.bin`) from Hugging Face; a compromised model repository could run code.
  Pin model revisions (commit hashes) where possible.
- **Installers are unsigned** (no Windows code signing) and commits are not signed.
- Tests and CI cannot prove the absence of malicious code; review is the control.
