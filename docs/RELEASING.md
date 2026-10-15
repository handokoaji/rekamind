🌐 **English** · [Bahasa Indonesia](RELEASING.id.md)

# Releasing

Releases are produced by `.github/workflows/release.yml` when a `v*` tag is pushed.
Tags ending in `-alpha.N`, `-beta.N` or `-rc.N` become a GitHub **pre-release**.

1. Sync the version in every file: `python scripts/set_version.py 0.4.0-beta.2`
   (Python uses the PEP 440 form `0.4.0b2` automatically; `--check` verifies).
2. Add a `CHANGELOG.md` entry and write `docs/release-notes/v0.4.0-beta.2.md` (English + Indonesian, honest about limitations).
3. Run the tests: `pytest server`, `cd web && npm test`, `cd recorder && cargo test`.
4. Commit, merge to `master`, then:
   ```bash
   git tag -a v0.4.0-beta.2 -m "Rekamind v0.4.0-beta.2"
   git push origin v0.4.0-beta.2
   ```
5. The workflow checks version = tag, builds the Windows (NSIS) and Linux (.deb, plus AppImage if it succeeds) installers,
   runs the frozen-backend smoke test, creates `SHA256SUMS.txt` and publishes the release. If a job fails nothing is
   published; fix it and re-run via *Actions → Release → Run workflow* (enter the same tag).
6. Download and try each installer on a clean machine before announcing.

App icons are generated from `docs/assets/logo.svg` (`scripts/make_icons.mjs`); the UI logo, favicon and README use the same shape.
README screenshots: `cd web && npm run build && npx playwright test -c playwright.docs.config.ts`.

Code signing (Windows Authenticode, GPG) is not configured yet; it is a prerequisite for a final release.
