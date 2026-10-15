🌐 **English** · [Bahasa Indonesia](CONTRIBUTING.id.md)

# Contributing

Rekamind is licensed under AGPL-3.0-or-later: anyone may use it, install it themselves, and copy it under those terms. Changes to this repo come in
through pull requests reviewed by a maintainer.

Before opening a PR, run whatever is relevant:

```bash
cd server && ruff check . && pytest -q
cd web && npx tsc -b --noEmit && npx vitest run
cd recorder && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

Rules that must not be broken:
- New API routes must use the current user and filter by owner. The route inventory test in
  `server/tests/test_auth.py` will fail if you forget.
- The recorder must stay lightweight: do not add heavy work or large dependencies in `recorder/`.
- Do not add default credentials or secrets to the repo.

## Licence of contributions

By opening a pull request you agree that your contribution is licensed under **AGPL-3.0-or-later**, and that you grant the
maintainer (handokoaji) a perpetual, worldwide, non-exclusive, royalty-free right to also distribute it under other
licences, including commercial ones (dual licensing). You confirm that you wrote it or have the right to submit it. This is
a short statement of terms, not a full CLA, and may be replaced by a formal CLA later.