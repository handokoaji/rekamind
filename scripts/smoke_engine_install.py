#!/usr/bin/env python3
"""Install an engine with the REAL frozen backend, the way the desktop app does (output through a pipe), and prove the
two things that once broke it on Windows (`OSError: [Errno 22]`, exit code 120):

  A. every byte the installer prints is valid UTF-8 (the app's reader stops at the first line that is not), and
  B. the install still succeeds when the reader goes away in the middle of the download (a closed pipe is Errno 22 on
     Windows and used to make pip report an install failure).

    python scripts/smoke_engine_install.py [--kind cpu] path/to/rekamind-backend[.exe]
    python scripts/smoke_engine_install.py --no-engines-prefix python -m rekamind_server.enginepack
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def launch(cmd: list[str], data_dir: Path) -> subprocess.Popen:
    env = {**os.environ, "REKAMIND_DATA_DIR": str(data_dir), "PIP_NO_CACHE_DIR": "1"}  # no cache: downloads must really happen
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)  # leave the console code page alone: that is what the app's users have
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW, like the app
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL, **flags)  # noqa: S603


def marker(data_dir: Path) -> dict | None:
    try:
        return json.loads((data_dir / "engine-pack" / "installed.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def scenario_a(cmd: list[str], kind: str, timeout: int) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        p = launch(cmd, data)
        raw = p.stdout.read()  # to EOF, like a reader that never stops
        code = p.wait(timeout=timeout)
        lines = raw.split(b"\n")
        text = ""
        for i, line in enumerate(lines):
            try:
                text += line.decode("utf-8") + "\n"
            except UnicodeDecodeError:
                problems.append(f"A: line {i} is not valid UTF-8: {line[:80]!r}")
        if code != 0:
            problems.append(f"A: exit code {code} (expected 0); tail:\n" + "\n".join(text.strip().splitlines()[-12:]))
        if "Errno 22" in text or "Exception ignored" in text:
            problems.append("A: output mentions Errno 22 / 'Exception ignored'")
        if not text.splitlines() or not text.splitlines()[0].startswith(("Lokasi pack:", "Rekamind")):
            problems.append(f"A: unexpected first line {text.splitlines()[:1]}")
        if "Rekamind " not in text or " build " not in text:
            problems.append("A: the build is not named in the diagnostics")
        if not any(ln.startswith("  ... ") for ln in text.splitlines()):
            problems.append("A: no progress line was printed (pip cache hit? the smoke needs real downloads)")
        if (marker(data) or {}).get("kind") != kind:
            problems.append(f"A: installed.json is {marker(data)}")
        print(f"A (reader reads everything): exit {code}, {len(lines)} lines, marker {marker(data)}", flush=True)
    return problems


def scenario_b(cmd: list[str], kind: str, timeout: int) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        p = launch(cmd, data)
        seen = threading.Event()
        closed = threading.Event()

        def reader() -> None:
            for line in iter(p.stdout.readline, b""):
                if line.startswith(b"  ... "):
                    seen.set()
                    break
            time.sleep(1)
            p.stdout.close()  # the reader dies in the middle of the install
            closed.set()

        threading.Thread(target=reader, daemon=True).start()
        code = p.wait(timeout=timeout)
        print(f"B (reader closed the pipe after the first progress line: {seen.is_set()}): exit {code}, marker {marker(data)}", flush=True)
        if not seen.is_set():
            problems.append("B: never reached a progress line, so the dead-reader case was not exercised")
        if code != 0:
            problems.append(f"B: exit code {code} after the reader went away (expected 0)")
        if (marker(data) or {}).get("kind") != kind:
            problems.append(f"B: installed.json is {marker(data)}: the install did not survive a dead reader")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="cpu")
    ap.add_argument("--no-engines-prefix", action="store_true")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("command", nargs=argparse.REMAINDER, help="the program (and its leading arguments) to run")
    a = ap.parse_args()
    if not a.command:
        ap.error("give the backend program to run")
    cmd = [*a.command, *([] if a.no_engines_prefix else ["engines"]), "install", a.kind]
    print("command:", cmd, flush=True)
    problems = scenario_a(cmd, a.kind, a.timeout) + scenario_b(cmd, a.kind, a.timeout)
    if problems:
        print("\nFAILED:\n" + "\n".join(problems), file=sys.stderr)
        return 1
    print("Engine install smoke passed: UTF-8 clean, and it survives a dead reader.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
