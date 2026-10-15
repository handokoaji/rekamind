🌐 **English** · [Bahasa Indonesia](CONTRIBUTING.id.md)

# Contributing

Rekamind is MIT licensed: anyone may use it, install it themselves, and copy it. Changes to this repo come in
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
