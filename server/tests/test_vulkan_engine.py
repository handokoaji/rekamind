"""whisper.cpp / Vulkan engine: real subprocess against a fake `whisper-cli`, real HTTP against a local file server."""
import hashlib
import http.server
import json
import stat
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from rekamind_server import engine_assets, enginepack
from rekamind_server.config import Settings
from rekamind_server.engines import whispercpp as wc
from rekamind_server.engines.registry import use_vulkan

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake whisper-cli is a POSIX script")

FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if "-h" in a:
    print("usage: whisper-cli [options]"); sys.exit(int(os.environ.get("FAKE_H_EXIT", "0")))
get = lambda f: a[a.index(f) + 1]
if os.environ.get("FAKE_FAIL"):
    print("ggml_vulkan: failed to init", file=sys.stderr); sys.exit(3)
if not os.environ.get("FAKE_NO_GPU"):
    print("ggml_vulkan: Found 2 Vulkan devices:", file=sys.stderr)
    print("ggml_vulkan: 0 = AMD Radeon(TM) 860M Graphics (AMD proprietary driver) | uma: 1 | fp16: 1", file=sys.stderr)
    print("ggml_vulkan: 1 = NVIDIA GeForce RTX 4060 (NVIDIA) | uma: 0 | fp16: 1", file=sys.stderr)
if "-of" in a:
    json.dump({"transcription": [
        {"offsets": {"from": 0, "to": 2400}, "text": " Selamat pagi semuanya."},
        {"offsets": {"from": 2400, "to": 3000}, "text": " [BLANK_AUDIO]"},
        {"offsets": {"from": 3000, "to": 7000}, "text": " Kita mulai rapat."},
        {"offsets": {"from": 7000, "to": 7100}, "text": "   "}]},
        open(get("-of") + ".json", "w"))
print("[00:00:00.000 --> 00:00:02.400]  Selamat pagi semuanya.")
'''


@pytest.fixture
def server(tmp_path):
    """Serves tmp_path/www over HTTP on loopback; returns (base_url, www_dir)."""
    www = tmp_path / "www"
    www.mkdir()

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(www), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", www
    srv.shutdown()


@pytest.fixture
def env(monkeypatch, tmp_path, server):
    base, www = server
    monkeypatch.setenv("REKAMIND_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_ALLOW_LOOPBACK", "1")
    monkeypatch.delenv("REKAMIND_WHISPERCPP_BIN", raising=False)
    monkeypatch.setattr(enginepack, "detect_gpus", lambda: [])
    return base, www


def publish(www: Path, base: str, *, tamper: bool = False) -> None:
    z = www / "whisper-vulkan.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("whisper-cli", FAKE_CLI)
        f.writestr("BUILD_INFO.json", json.dumps({"whispercpp_tag": "v1.9.5"}))
    digest = hashlib.sha256(z.read_bytes()).hexdigest()
    if tamper:
        digest = "0" * 64
    key = engine_assets.platform_key()
    (www / "manifest.json").write_text(json.dumps({"schema": 1, "whispercpp": {"version": "v1.9.5", "assets": {
        key: {"url": f"{base}/whisper-vulkan.zip", "sha256": digest}}}}))


def test_url_policy():
    assert engine_assets.check_url("https://github.com/x/y.zip")
    assert engine_assets.check_url("https://huggingface.co/a/b.bin")
    for bad in ("http://github.com/x", "https://evil.example/x.zip", "file:///etc/passwd", "https://github.com.evil.example/x"):
        with pytest.raises(engine_assets.AssetError):
            engine_assets.check_url(bad)


def test_zip_slip_is_rejected(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(engine_assets.AssetError, match="berbahaya"):
        engine_assets.safe_extract(z, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_install_downloads_verifies_and_makes_the_program_runnable(env, tmp_path, monkeypatch):
    base, www = env
    publish(www, base)
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_URL", f"{base}/manifest.json")
    pack = tmp_path / "data" / "engine-pack"
    pack.mkdir(parents=True)
    exe = engine_assets.install_program(pack, log=lambda m: None)
    assert exe.name == "whisper-cli" and exe.stat().st_mode & stat.S_IXUSR
    assert engine_assets.find_binary(pack) == exe


def test_checksum_mismatch_installs_nothing(env, tmp_path, monkeypatch):
    base, www = env
    publish(www, base, tamper=True)
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_URL", f"{base}/manifest.json")
    pack = tmp_path / "data" / "engine-pack"
    pack.mkdir(parents=True)
    with pytest.raises(engine_assets.AssetError, match="SHA-256"):
        engine_assets.install_program(pack, log=lambda m: None)
    assert engine_assets.find_binary(pack) is None and not list(pack.glob("*.part")) and not (pack / "whispercpp.zip").exists()


def test_manifest_with_unknown_schema_or_platform(env, monkeypatch, tmp_path):
    base, www = env
    (www / "manifest.json").write_text(json.dumps({"schema": 2}))
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_URL", f"{base}/manifest.json")
    with pytest.raises(engine_assets.AssetError, match="skema"):
        engine_assets.fetch_manifest()
    with pytest.raises(engine_assets.AssetError, match="Tidak ada paket"):
        engine_assets.pick_asset({"whispercpp": {"assets": {}}}, "windows-x64")


def test_model_download_falls_back_to_the_plain_file_when_the_quantised_one_is_missing(env, monkeypatch):
    base, www = env
    (www / "ggml-small.bin").write_bytes(b"x" * 2_000_000)  # only the plain model exists
    monkeypatch.setattr(engine_assets, "MODEL_REPO_URL", base)
    got = engine_assets.ensure_model("small", "q5_1", log=lambda m: None)
    assert got.name == "ggml-small.bin" and got.stat().st_size == 2_000_000
    assert engine_assets.existing_model("small", "q5_1") == got  # cached: no second download
    assert engine_assets.model_files("large-v3", "q5_0") == ["ggml-large-v3-q5_0.bin", "ggml-large-v3.bin"]
    assert engine_assets.model_files("ggml-medium.bin", "none") == ["ggml-medium.bin"]


@pytest.fixture
def installed(env, tmp_path, monkeypatch):
    base, www = env
    publish(www, base)
    (www / "ggml-large-v3-q5_0.bin").write_bytes(b"m" * 2_000_000)
    monkeypatch.setattr(engine_assets, "MODEL_REPO_URL", base)
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_URL", f"{base}/manifest.json")
    assert enginepack.install("vulkan") == 0
    return tmp_path / "data" / "engine-pack"


def test_cli_install_writes_the_marker_and_status_reports_it(installed):
    s = enginepack.status()
    assert s["kind"] == "vulkan" and s["asr"] is True
    assert use_vulkan(Settings(whisper_device="auto")) and use_vulkan(Settings(whisper_device="vulkan"))
    assert not use_vulkan(Settings(whisper_device="cuda"))


def test_check_reports_the_vulkan_device_once_a_model_is_cached(installed):
    first = enginepack.check()
    assert first["ok"] is True and first["gpu"] is False and "Belum ada model" in first["note"] and first["whispercpp"] == "v1.9.5"
    assert enginepack.warmup("large-v3") == 0
    got = enginepack.check()
    assert got["ok"] and got["gpu"] and got["vulkan_devices"][0].startswith("AMD Radeon(TM) 860M")
    assert got["model_cached"] == "ggml-large-v3-q5_0.bin"


def test_check_flags_a_program_that_crashes(installed, monkeypatch):
    monkeypatch.setenv("FAKE_H_EXIT", "139")
    got = enginepack.check()
    assert got["ok"] is False and "139" in got["error"]


def test_transcribe_returns_clean_segments_and_names_the_gpu(installed, tmp_path):
    enginepack.warmup("large-v3")
    t = wc.WhisperCppTranscriber(installed, "large-v3", "q5_0", device=0)
    segs = t.transcribe(tmp_path / "m.wav", "id")
    assert [(s.start_ms, s.end_ms, s.text) for s in segs] == [(0, 2400, "Selamat pagi semuanya."), (3000, 7000, "Kita mulai rapat.")]
    assert t.active_device.startswith("AMD Radeon(TM) 860M")
    wc.WhisperCppTranscriber(installed, "large-v3", "q5_0", device=1).transcribe(tmp_path / "m.wav", "id")


def test_second_device_index_is_reported(installed, tmp_path):
    enginepack.warmup("large-v3")
    t = wc.WhisperCppTranscriber(installed, "large-v3", "q5_0", device=1)
    t.transcribe(tmp_path / "m.wav", "id")
    assert t.active_device.startswith("NVIDIA GeForce RTX 4060")


def test_no_vulkan_device_is_reported_as_cpu(installed, tmp_path, monkeypatch):
    enginepack.warmup("large-v3")
    monkeypatch.setenv("FAKE_NO_GPU", "1")
    t = wc.WhisperCppTranscriber(installed, "large-v3", "q5_0")
    assert t.transcribe(tmp_path / "m.wav", "id") and t.active_device == "CPU"


def test_program_failure_and_missing_program_are_clear_errors(installed, tmp_path, monkeypatch):
    enginepack.warmup("large-v3")
    monkeypatch.setenv("FAKE_FAIL", "1")
    with pytest.raises(RuntimeError, match="kode 3"):
        wc.WhisperCppTranscriber(installed, "large-v3", "q5_0").transcribe(tmp_path / "m.wav", "id")
    with pytest.raises(RuntimeError, match="belum dipasang"):
        wc.WhisperCppTranscriber(tmp_path / "nowhere", "large-v3", "q5_0").transcribe(tmp_path / "m.wav", "id")


def test_parse_helpers():
    assert wc.parse_devices("noise\nggml_vulkan: 0 = Intel(R) Arc(TM) Graphics (Intel open-source Mesa driver) | uma: 1\n") == ["Intel(R) Arc(TM) Graphics"]
    assert wc.parse_devices("no vulkan here") == []
    assert wc.parse_segments({"transcription": [{"offsets": {"from": 5, "to": 5}, "text": " ok"}]})[0].end_ms == 6


def test_tls_context_keeps_system_roots_and_only_adds_certifi(monkeypatch):
    """An office that inspects TLS with its own CA must keep working: the system store is not replaced by certifi's."""
    import ssl

    calls = []

    class Ctx:
        def load_verify_locations(self, cafile=None, **k):
            calls.append(cafile)

    made = []
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: made.append((a, k)) or Ctx())
    engine_assets._ssl_context()
    assert made == [((), {})]  # the plain default context: system store / SSL_CERT_FILE untouched
    assert len(calls) == 1 and calls[0].endswith("cacert.pem")  # certifi added on top
