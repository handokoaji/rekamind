"""Samakan versi di semua berkas v2 dari satu angka SemVer.

    python scripts/set_version.py 0.4.0-beta.1     # tulis
    python scripts/set_version.py --check 0.4.0-beta.1   # keluar 1 bila ada yang beda

Python memakai PEP 440 (0.4.0b1); yang lain memakai SemVer apa adanya.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$")


def pep440(v: str) -> str:
    m = SEMVER.match(v)
    base = f"{m[1]}.{m[2]}.{m[3]}"
    return base + ({"alpha": "a", "beta": "b", "rc": "rc"}[m[4]] + m[5] if m[4] else "")


def _sub(text: str, pattern: str, repl: str, path: Path, many: bool = False) -> str:
    new, n = re.subn(pattern, repl, text, count=0 if many else 1, flags=re.M)
    if n < 1 or (n != 1 and not many):
        raise SystemExit(f"pola tidak ditemukan di {path}: {pattern}")
    return new


def targets(v: str) -> list[tuple[Path, str, str]]:
    """(berkas, pola, pengganti). Pola menangkap awalan di grup 1."""
    py = pep440(v)
    t = [
        (ROOT / "server/pyproject.toml", r'^(version = ")[^"]+(")', rf"\g<1>{py}\2"),
        (ROOT / "server/rekamind_server/__init__.py", r'^(__version__ = ")[^"]+(")', rf"\g<1>{py}\2"),
        (ROOT / "recorder/Cargo.toml", r'^(version = ")[^"]+(")', rf"\g<1>{v}\2"),
        (ROOT / "desktop/src-tauri/Cargo.toml", r'^(version = ")[^"]+(")', rf"\g<1>{v}\2"),
        (ROOT / "desktop/src-tauri/tauri.conf.json", r'^(  "version": ")[^"]+(")', rf"\g<1>{v}\2"),
    ]
    for pkg in ("web", "desktop"):
        t.append((ROOT / pkg / "package.json", r'^(  "version": ")[^"]+(")', rf"\g<1>{v}\2"))
    # Defaults users copy-paste: prebuilt-image tag in the compose files, download links and badge in the READMEs.
    for f, suffix in (("docker-compose.image.yml", "cpu"), ("docker-compose.image-gpu.yml", "cuda")):
        t.append((ROOT / f, rf"(REKAMIND_IMAGE_TAG:-)[^}}]+?(-{suffix}\}})", rf"\g<1>{v}\2"))
    for f in ("README.md", "README.id.md"):
        t.append((ROOT / f, r"(releases/(?:download|tag)/v)[^/)\s]+", rf"\g<1>{v}"))
        t.append((ROOT / f, r"(badge/(?:release|rilis)-v)[^-]+(?:--[a-z]+\.\d+)?(-f59e0b)", rf"\g<1>{v.replace('-', '--')}\2"))
    return t


CARGO_LOCKS = [(ROOT / "recorder/Cargo.lock", "rekamind-recorder"), (ROOT / "desktop/src-tauri/Cargo.lock", None)]


def lock_pattern(name: str) -> str:
    return rf'(name = "{re.escape(name)}"\nversion = ")[^"]+(")'


def cargo_names() -> dict[Path, str]:
    out = {}
    for lock, _ in CARGO_LOCKS:
        toml = lock.with_name("Cargo.toml")
        out[lock] = re.search(r'^name = "([^"]+)"', toml.read_text(encoding="utf-8"), re.M)[1]
    return out


def npm_lock(path: Path, v: str, write: bool) -> bool:
    d = json.loads(path.read_text(encoding="utf-8"))
    ok = d.get("version") == v and d["packages"][""]["version"] == v
    if write and not ok:
        d["version"] = v
        d["packages"][""]["version"] = v
        path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not SEMVER.match(a.version):
        print("versi harus X.Y.Z atau X.Y.Z-(alpha|beta|rc).N", file=sys.stderr)
        return 2
    bad = []
    for path, pat, repl in targets(a.version):
        text = path.read_text(encoding="utf-8")
        new = _sub(text, pat, repl, path, many=path.name.startswith("README"))
        if new != text:
            bad.append(path)
            if not a.check:
                path.write_text(new, encoding="utf-8")
    for lock, name in cargo_names().items():
        text = lock.read_text(encoding="utf-8")
        new = _sub(text, lock_pattern(name), rf"\g<1>{a.version}\2", lock)
        if new != text:
            bad.append(lock)
            if not a.check:
                lock.write_text(new, encoding="utf-8")
    for pkg in ("web", "desktop"):
        if not npm_lock(ROOT / pkg / "package-lock.json", a.version, write=not a.check):
            bad.append(ROOT / pkg / "package-lock.json")
    if a.check and bad:
        print("versi tidak sama:", *[str(p.relative_to(ROOT)) for p in bad], sep="\n  ")
        return 1
    print(("OK semua sama" if a.check else f"diperbarui: {len(bad)} berkas") + f" -> {a.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
