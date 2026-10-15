#!/usr/bin/env python3
"""Build the desktop installer *with* the local backend inside it.

    python scripts/build_desktop.py [--bundles nsis|deb|appimage] [--skip-web] [--skip-freeze]

Steps: build the web UI -> freeze the backend with PyInstaller (no ML libraries; they are installed
on demand) -> copy it to desktop/src-tauri/resources/backend -> `tauri build` with the bundle config
that ships that folder. Needs: node, a Python with `pip install -e "server[dev]" pyinstaller`, and a
Rust toolchain. A plain `cargo build` / `tauri dev` does not need any of this: without the bundled
backend the app falls back to `python -m rekamind_server`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "desktop" / "src-tauri" / "resources" / "backend"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}   (in {cwd.relative_to(ROOT)})", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def write_buildinfo() -> str:
    """Record the commit in the package before freezing, so a user's log and the engine panel name the exact build."""
    import os

    sha = (os.environ.get("GITHUB_SHA") or "")[:7]
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT, capture_output=True, text=True,  # noqa: S607
                                 check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            sha = "unknown"
    (ROOT / "server" / "rekamind_server" / "_buildinfo.py").write_text(f'COMMIT = "{sha}"\n', encoding="utf-8")
    print(f"build {sha}", flush=True)
    return sha


def require_tools() -> bool:
    """Say what is missing before a 5-minute build dies with a cryptic error halfway."""
    missing = []
    for tool, hint in (("node", "Node 22+ (nodejs.org)"), ("cargo", "Rust (rustup.rs); buka terminal baru atau tambahkan ~/.cargo/bin ke PATH"),
                       (NPM, "npm (ikut Node)")):
        if shutil.which(tool) is None:
            missing.append(f"  - `{tool}` tidak ditemukan di PATH: pasang {hint}")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        missing.append("  - PyInstaller belum terpasang di Python ini: `pip install pyinstaller` (dan aktifkan venv proyek)")
    if missing:
        print("Prasyarat build belum lengkap:\n" + "\n".join(missing), file=sys.stderr)
    return not missing


def main() -> int:
    if not require_tools():
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", default="nsis" if sys.platform == "win32" else "deb")
    ap.add_argument("--skip-web", action="store_true")
    ap.add_argument("--skip-freeze", action="store_true")
    a = ap.parse_args()

    if not a.skip_web:
        run([NPM, "ci"], ROOT / "web")
        run([NPM, "run", "build"], ROOT / "web")
    if not a.skip_freeze:
        write_buildinfo()
        dist, work = ROOT / "server" / "build" / "dist", ROOT / "server" / "build" / "work"
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(dist), "--workpath", str(work),
             "packaging/rekamind-backend.spec"], ROOT / "server")
        if RES.exists():
            shutil.rmtree(RES)
        shutil.copytree(dist / "rekamind-backend", RES)
    exe = RES / ("rekamind-backend.exe" if sys.platform == "win32" else "rekamind-backend")
    if not exe.is_file():
        print(f"Backend beku tidak ada di {exe}. Jalankan tanpa --skip-freeze.", file=sys.stderr)
        return 1
    run([NPM, "ci"], ROOT / "desktop")
    run([NPX, "tauri", "build", "--bundles", a.bundles, "--config", "src-tauri/tauri.bundle.conf.json"], ROOT / "desktop")
    print("\nSelesai. Installer ada di desktop/src-tauri/target/release/bundle/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
