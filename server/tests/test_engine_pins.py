"""The engine program is pinned by hash in the app (engine_pins.py): what is installed, what is refused."""
import hashlib
import http.server
import json
import threading
import zipfile
from pathlib import Path

import pytest

from rekamind_server import engine_assets, engine_pins


@pytest.fixture
def www(tmp_path):
    root = tmp_path / "www"
    root.mkdir()

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()


@pytest.fixture(autouse=True)
def loopback(monkeypatch):
    monkeypatch.setenv("REKAMIND_ENGINE_ASSETS_ALLOW_LOOPBACK", "1")


def make_zip(root: Path, body: bytes = b"program") -> Path:
    z = root / "engine.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr(engine_assets.binary_name(), body)
    return z


def pin(monkeypatch, base: str, z: Path, **override) -> None:
    entry = {"url": f"{base}/engine.zip", "sha256": hashlib.sha256(z.read_bytes()).hexdigest(), "size": z.stat().st_size}
    entry.update(override)
    monkeypatch.setattr(engine_pins, "PINS", {engine_pins.DEFAULT_VERSION: {engine_assets.platform_key(): entry}})


def test_shipped_pins_are_well_formed():
    assert engine_pins.DEFAULT_VERSION in engine_pins.PINS
    for version, platforms in engine_pins.PINS.items():
        assert {"windows-x64", "linux-x64"} <= set(platforms), version
        for key, a in platforms.items():
            assert len(a["sha256"]) == 64 and set(a["sha256"]) <= set("0123456789abcdef"), (version, key)
            assert a["size"] > 1_000_000, (version, key)
            engine_assets.check_url(a["url"])  # https + allow-listed host
    for key in ("windows-x64", "linux-x64"):
        assert engine_assets.pinned_asset(key)["sha256"]


def test_install_with_the_pinned_hash_works_and_never_reads_a_manifest(www, tmp_path, monkeypatch):
    base, root = www
    z = make_zip(root)
    pin(monkeypatch, base, z)
    (root / "manifest.json").write_text("this is not even json")  # a hostile or broken manifest must be irrelevant
    pack = tmp_path / "pack"
    pack.mkdir()
    exe = engine_assets.install_program(pack, log=lambda m: None)
    assert exe.name == engine_assets.binary_name() and exe.read_bytes() == b"program"
    assert engine_assets.find_binary(pack) == exe


def test_a_replaced_release_is_refused(www, tmp_path, monkeypatch):
    """The attack this exists for: the file on the release is swapped, and its own manifest would even agree."""
    base, root = www
    good = make_zip(root, b"program")
    pin(monkeypatch, base, good)  # the app trusts the hash of the good build
    evil = make_zip(root, b"progrAm")  # same URL, same length, different bytes: only the hash can tell
    asset = {"url": f"{base}/engine.zip", "sha256": hashlib.sha256(evil.read_bytes()).hexdigest()}
    (root / "manifest.json").write_text(json.dumps({"schema": 1, "whispercpp": {"assets": {engine_assets.platform_key(): asset}}}))
    pack = tmp_path / "pack"
    pack.mkdir()
    with pytest.raises(engine_assets.AssetError, match="SHA-256"):
        engine_assets.install_program(pack, log=lambda m: None)
    assert engine_assets.find_binary(pack) is None
    assert not list(pack.glob("*.part")) and not (pack / "whispercpp.zip").exists()


def test_wrong_size_is_refused(www, tmp_path, monkeypatch):
    base, root = www
    z = make_zip(root)
    pin(monkeypatch, base, z, size=z.stat().st_size + 1)
    pack = tmp_path / "pack"
    pack.mkdir()
    with pytest.raises(engine_assets.AssetError, match="Ukuran"):
        engine_assets.install_program(pack, log=lambda m: None)
    assert engine_assets.find_binary(pack) is None and not (pack / "whispercpp.zip").exists()


def test_no_pin_means_no_install(monkeypatch):
    monkeypatch.setattr(engine_pins, "PINS", {})
    with pytest.raises(engine_assets.AssetError, match="Perbarui Rekamind"):
        engine_assets.pinned_asset("windows-x64")
    monkeypatch.setattr(engine_pins, "PINS", {engine_pins.DEFAULT_VERSION: {"windows-x64": {"url": "https://github.com/x", "sha256": "xyz"}}})
    with pytest.raises(engine_assets.AssetError, match="tidak valid"):
        engine_assets.pinned_asset("windows-x64")


def test_a_pin_pointing_off_the_allow_list_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("REKAMIND_ENGINE_ASSETS_ALLOW_LOOPBACK")
    monkeypatch.setattr(engine_pins, "PINS", {engine_pins.DEFAULT_VERSION: {engine_assets.platform_key(): {
        "url": "https://evil.example/engine.zip", "sha256": "0" * 64, "size": 1}}})
    pack = tmp_path / "pack"
    pack.mkdir()
    with pytest.raises(engine_assets.AssetError, match="tidak diizinkan"):
        engine_assets.install_program(pack, log=lambda m: None)