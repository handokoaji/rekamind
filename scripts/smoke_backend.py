#!/usr/bin/env python3
"""Smoke-test a frozen backend (the one inside the installer). Standard library only.

    python scripts/smoke_backend.py path/to/rekamind-backend[.exe]

Starts it the way the desktop app does (local-token mode, fake engines, throwaway data dir), then
checks: it comes up and migrates, it refuses requests without the secret, a recording goes through
the whole pipeline, and the `engines` sub-commands answer. Exit code 0 = good.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

TOKEN = "smoke-" + "x" * 40


def wav(seconds: int = 1) -> bytes:
    n = 16000 * seconds
    data = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def call(base: str, method: str, path: str, body: bytes | None = None, token: str | None = TOKEN, ctype: str = "application/json"):
    req = urllib.request.Request(base + path, data=body, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def main(exe: str) -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    data = tempfile.mkdtemp(prefix="rekamind-smoke-")
    env = {**os.environ, "REKAMIND_AUTH": "local_token", "REKAMIND_LOCAL_TOKEN": TOKEN, "REKAMIND_PORT": str(port),
           "REKAMIND_ENGINES": "fake", "REKAMIND_DATA_DIR": data, "REKAMIND_ENGINE_PACK": os.path.join(data, "engine-pack"),
           "REKAMIND_WORKER_POLL_SECONDS": "0.2"}
    base = f"http://127.0.0.1:{port}"
    log = open(os.path.join(data, "backend.log"), "w")  # noqa: SIM115
    p = subprocess.Popen([exe], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            if p.poll() is not None:
                print(open(log.name).read()[-2000:])
                check(False, f"backend exited early ({p.returncode})")
            try:
                if call(base, "GET", "/api/health", token=None)[0] == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                pass
            time.sleep(0.3)
        else:
            check(False, "backend did not come up within 60 s")
        check(True, f"up in {time.time() - t0:.1f}s (migrations ran)")
        check(call(base, "GET", "/api/meetings", token=None)[0] == 401, "refuses requests without the local secret")
        check(call(base, "GET", "/api/meetings", token="wrong")[0] == 401, "refuses a wrong secret")
        st, m = call(base, "POST", "/api/meetings", json.dumps({"title": "Smoke", "language": "id"}).encode())
        check(st == 201, "creates a meeting")
        mid = m["id"]
        for src in ("mic", "speaker"):
            check(call(base, "PUT", f"/api/meetings/{mid}/audio/{src}", wav(), ctype="application/octet-stream")[0] == 201, f"accepts {src} audio")
        check(call(base, "POST", f"/api/meetings/{mid}/finish")[0] == 200, "finishes")
        check(call(base, "POST", f"/api/meetings/{mid}/process")[0] == 202, "queues processing")
        status = ""
        for _ in range(100):
            status = call(base, "GET", f"/api/meetings/{mid}")[1]["status"]
            if status in ("review", "done", "failed"):
                break
            time.sleep(0.3)
        check(status in ("review", "done"), f"pipeline finished (status={status})")
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
    r = subprocess.run([exe, "engines", "status"], env=env, capture_output=True, text=True, timeout=60)
    doc = json.loads(r.stdout.strip().splitlines()[-1])
    check(doc["asr"] is False and doc["kind"] is None, "engines status answers (nothing installed in a fresh data dir)")
    r = subprocess.run([exe, "engines", "check"], env=env, capture_output=True, text=True, timeout=60)
    doc = json.loads(r.stdout.strip().splitlines()[-1])
    check(doc["ok"] is False and "error" in doc, "engines check reports a missing pack instead of crashing")
    check(subprocess.run([exe, "engines", "install", "--help"], env=env, capture_output=True, timeout=60).returncode == 0, "pip is bundled for the engine install")
    print("\nSmoke test lulus.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
