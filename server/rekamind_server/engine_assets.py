"""Downloading the prebuilt whisper.cpp (Vulkan) program and its models, with verification.

The Vulkan engine is a small native program (`whisper-cli`) built by this project's CI from a pinned whisper.cpp
release and published as a GitHub release asset next to a `manifest.json` that lists, per platform, its URL and
SHA-256. The program is verified against that hash before it is unpacked. The manifest and the program come from
the same release, so this guards against corrupt or truncated downloads and tampering in transit, not against a
compromised release; see SECURITY.md. Models are plain files from the whisper.cpp Hugging Face repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

MANIFEST_URL = "https://github.com/handokoaji/rekamind/releases/download/engine-assets/manifest.json"
MODEL_REPO_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
ALLOWED_HOSTS = ("github.com", "githubusercontent.com", "huggingface.co", "hf.co")
CHUNK = 1024 * 1024


class AssetError(RuntimeError):
    pass


def platform_key() -> str:
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise AssetError(f"Platform {platform.system()}/{machine} belum didukung untuk mesin Vulkan (hanya x64).")
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    raise AssetError(f"Sistem {sys.platform} belum didukung untuk mesin Vulkan.")


def _ssl_context() -> ssl.SSLContext:
    """The system trust store (and SSL_CERT_FILE) first, so an office network that inspects TLS with its own CA
    works; certifi's roots are *added* for builds with no usable system store (never replace the system roots)."""
    ctx = ssl.create_default_context()
    try:
        import certifi  # bundled with the frozen backend

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:  # noqa: BLE001, S110 - the system store alone is fine
        pass
    return ctx


def check_url(url: str) -> str:
    """Only https, only the hosts we expect (the manifest is data, never trusted to point anywhere)."""
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    if os.environ.get("REKAMIND_ENGINE_ASSETS_ALLOW_LOOPBACK") == "1" and u.scheme == "http" and host in ("127.0.0.1", "localhost"):
        return url  # tests only: never set in a real install
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise AssetError(f"Alamat unduhan tidak diizinkan: {url}")
    return url


def _open(url: str, timeout: float = 30):
    req = urllib.request.Request(check_url(url), headers={"User-Agent": "rekamind-engine-assets"})  # noqa: S310
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())  # noqa: S310 - https + allow-list above


def manifest_url() -> str:
    return os.environ.get("REKAMIND_ENGINE_ASSETS_URL") or MANIFEST_URL


def fetch_manifest() -> dict:
    try:
        with _open(manifest_url()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AssetError(f"Tidak bisa mengambil daftar mesin dari {manifest_url()}: {e}") from e
    if data.get("schema") != 1 or "whispercpp" not in data:
        raise AssetError("Daftar mesin tidak dikenali (skema berbeda). Perbarui Rekamind.")
    return data


def pick_asset(manifest: dict, key: str | None = None) -> dict:
    key = key or platform_key()
    asset = manifest["whispercpp"].get("assets", {}).get(key)
    if not asset or not asset.get("url") or not asset.get("sha256"):
        raise AssetError(f"Tidak ada paket whisper.cpp untuk {key} di daftar mesin.")
    return asset


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str | None = None, log: Callable[[str], None] = print,
             every: float = 4.0) -> Path:
    """Stream to `dest.part`, report progress every few seconds (a silent 1 GB download looks like a hang), verify,
    then move into place. Never leaves a half-written `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done, last = 0, time.monotonic()
    try:
        with _open(url, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(CHUNK):
                f.write(chunk)
                done += len(chunk)
                if time.monotonic() - last >= every:
                    last = time.monotonic()
                    pct = f" ({done * 100 // total}%)" if total else ""
                    log(f"  ... {done / 1e6:,.0f} MB{pct}")
        if total and done != total:
            raise AssetError(f"Unduhan terputus ({done} dari {total} byte).")
        if sha256 and sha256_file(part).lower() != sha256.lower():
            raise AssetError("Checksum SHA-256 tidak cocok: berkas rusak atau diubah. Unduhan dibatalkan.")
        os.replace(part, dest)
    except (urllib.error.URLError, OSError) as e:
        raise AssetError(f"Unduhan gagal: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    return dest


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract without letting an entry write outside `dest` (zip-slip)."""
    dest = dest.resolve()
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise AssetError(f"Paket berisi jalur berbahaya: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
            out.append(target)
    return out


def binary_name() -> str:
    return "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"


def find_binary(pack: Path) -> Path | None:
    """The program inside the pack's `whispercpp` folder (any depth), or the REKAMIND_WHISPERCPP_BIN override."""
    env = os.environ.get("REKAMIND_WHISPERCPP_BIN")
    if env:
        p = Path(env)
        return p if p.is_file() else None
    root = pack / "whispercpp"
    if not root.is_dir():
        return None
    for p in root.rglob(binary_name()):
        return p
    return None


def install_program(pack: Path, log: Callable[[str], None] = print) -> Path:
    """Fetch the manifest, download the program for this platform, verify, unpack into `pack/whispercpp`."""
    log(f"Mengambil daftar mesin: {manifest_url()}")
    manifest = fetch_manifest()
    asset = pick_asset(manifest)
    wc = manifest["whispercpp"]
    log(f"whisper.cpp {wc.get('version', '?')} untuk {platform_key()} (SHA-256 {asset['sha256'][:12]}...)")
    target = pack / "whispercpp"
    zip_path = pack / "whispercpp.zip"
    download(asset["url"], zip_path, asset["sha256"], log)
    try:
        if target.exists():
            import shutil

            shutil.rmtree(target)
        safe_extract(zip_path, target)
    finally:
        zip_path.unlink(missing_ok=True)
    exe = find_binary(pack)
    if exe is None:
        raise AssetError("Paket terunduh tetapi whisper-cli tidak ada di dalamnya.")
    if sys.platform != "win32":
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


# ---- models --------------------------------------------------------------------------------------------------
def models_dir() -> Path:
    return Path(os.environ.get("REKAMIND_DATA_DIR") or Path.home() / ".rekamind") / "whispercpp-models"


def model_files(name: str, quant: str) -> list[str]:
    """File names to try, best first. Not every size has every quantisation, so the plain model is the fallback."""
    name = name.removeprefix("ggml-").removesuffix(".bin")
    files = []
    if quant and quant != "none":
        files.append(f"ggml-{name}-{quant}.bin")
    files.append(f"ggml-{name}.bin")
    return files


def existing_model(name: str, quant: str) -> Path | None:
    for f in model_files(name, quant):
        p = models_dir() / f
        if p.is_file() and p.stat().st_size > 1_000_000:
            return p
    return None


def ensure_model(name: str, quant: str, log: Callable[[str], None] = print) -> Path:
    """The model file, downloading it first if it is not cached yet."""
    have = existing_model(name, quant)
    if have:
        return have
    last: Exception | None = None
    for f in model_files(name, quant):
        url = f"{MODEL_REPO_URL}/{f}"
        log(f"Mengunduh model {f} (bisa ratusan MB sampai beberapa GB) ...")
        try:
            return download(url, models_dir() / f, None, log)
        except AssetError as e:
            last = e
            log(f"  tidak tersedia ({e}); mencoba varian lain")
    raise AssetError(f"Model {name} tidak bisa diunduh: {last}")
