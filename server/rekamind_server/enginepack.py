"""The optional "engine pack": faster-whisper (+ pyannote) installed *next to* the frozen backend.

The desktop installer ships a small backend (API, queue, SQLite, audio decoding). The machine-learning
libraries are several GB and depend on the hardware (CPU or NVIDIA), so they are installed on demand
into a user folder and put on `sys.path` before the engines are imported. This module is also usable
from a normal Python install (`python -m rekamind_server.enginepack status`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

TORCH_INDEX = {"cpu": "https://download.pytorch.org/whl/cpu", "cuda": "https://download.pytorch.org/whl/cu126"}
# Pins follow the v1 README (torch 2.13 / cu126); ctranslate2 comes in through faster-whisper.
PACKAGES = {
    "asr": ["faster-whisper>=1.0", "soundfile>=0.12"],
    "diarize": ["pyannote.audio>=4.0", "soundfile>=0.12"],
    # faster-whisper on NVIDIA needs the CUDA 12 runtime libraries next to it.
    "cuda_runtime": ["nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"],
}


def default_pack_dir() -> Path:
    env = os.environ.get("REKAMIND_ENGINE_PACK")
    if env:
        return Path(env)
    return Path(os.environ.get("REKAMIND_DATA_DIR") or Path.home() / ".rekamind") / "engine-pack"


def activate(pack: Path | None = None) -> Path:
    """Make the pack importable. Safe to call repeatedly and when the pack does not exist yet."""
    pack = pack or default_pack_dir()
    p = str(pack)
    if pack.is_dir() and p not in sys.path:
        sys.path.insert(0, p)
    if sys.platform == "win32" and pack.is_dir():
        # Native DLLs (torch, ctranslate2, cuDNN) are no longer found through PATH on Python 3.8+.
        for d in [pack / "torch" / "lib", pack / "ctranslate2", *pack.glob("nvidia/*/bin")]:
            if d.is_dir():
                os.add_dll_directory(str(d))
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    elif pack.is_dir():
        # Linux: the nvidia-* wheels ship .so files that ctranslate2 finds through the loader path.
        libs = [str(d) for d in pack.glob("nvidia/*/lib")]
        if libs:
            os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(libs + [os.environ.get("LD_LIBRARY_PATH", "")]).rstrip(os.pathsep)
    return pack


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def status(pack: Path | None = None) -> dict:
    """Cheap and import-free (nothing heavy is loaded just to answer 'is it installed?')."""
    pack = activate(pack)
    marker = pack / "installed.json"
    meta: dict = {}
    if marker.is_file():
        try:
            meta = json.loads(marker.read_text("utf-8"))
        except (OSError, ValueError):
            meta = {}
    return {
        "pack_dir": str(pack),
        "asr": _has("faster_whisper"),
        "diarize": _has("pyannote.audio") or _has("pyannote"),
        "kind": meta.get("kind"),  # "cpu" | "cuda" | None
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def _bundled_pins() -> list[str]:
    """numpy and av are already inside the frozen backend; the pack must agree with them, not shadow them."""
    from importlib import metadata

    pins = []
    for name in ("numpy", "av"):
        try:
            pins.append(f"{name}=={metadata.version(name)}")
        except metadata.PackageNotFoundError:
            pass
    return pins


def check(pack: Path | None = None) -> dict:
    """Actually import the engines (unlike `status`) so a broken install is caught here, not mid-meeting."""
    activate(pack)
    out: dict = {"ok": False, "cuda_devices": 0, "error": None}
    try:
        import ctranslate2
        import faster_whisper

        out["ctranslate2"] = ctranslate2.__version__
        out["faster_whisper"] = faster_whisper.__version__
        out["cuda_devices"] = int(ctranslate2.get_cuda_device_count())
        out["ok"] = True
    except Exception as e:  # noqa: BLE001 - report, never crash the caller
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def pip_args(kind: str, pack: Path, with_diarize: bool, pins: list[str] | None = None) -> list[str]:
    if kind not in TORCH_INDEX:
        raise ValueError("kind harus 'cpu' atau 'cuda'")
    pkgs = list(PACKAGES["asr"])
    if kind == "cuda":
        pkgs += PACKAGES["cuda_runtime"]
    if with_diarize:
        pkgs += PACKAGES["diarize"]
    # torch comes from the hardware-specific index; everything else still resolves from PyPI.
    return ["install", "--target", str(pack), "--upgrade", "--only-binary=:all:", "--disable-pip-version-check",
            "--no-input", "--progress-bar", "off", "--root-user-action=ignore",
            # pip also inspects the frozen app's own metadata and would print scary, irrelevant "ERROR:" conflicts.
            "--no-warn-conflicts",
            # Only pyannote needs torch. faster-whisper (ctranslate2) does not, and querying the extra index
            # for every package would slow the install and fail wherever download.pytorch.org is blocked.
            *(["--extra-index-url", TORCH_INDEX[kind]] if with_diarize else []),
            *pkgs, *(pins or [])]


def install(kind: str, with_diarize: bool = False, pack: Path | None = None) -> int:
    """Run pip *inside this interpreter* (works from the frozen backend too). Output goes to stdout."""
    pack = pack or default_pack_dir()
    pack.mkdir(parents=True, exist_ok=True)
    from pip._internal.cli.main import (
        main as pip_main,  # bundled with the frozen backend
    )

    code = int(pip_main(pip_args(kind, pack, with_diarize, _bundled_pins())) or 0)
    if code == 0:
        (pack / "installed.json").write_text(json.dumps({"kind": kind, "diarize": with_diarize}), "utf-8")
    return code


def warmup(model: str, pack: Path | None = None) -> int:
    """Download the Whisper weights now (instead of at the first meeting). Needs the pack installed."""
    activate(pack)
    from faster_whisper.utils import download_model

    print(f"Mengunduh model {model} …", flush=True)
    path = download_model(model, cache_dir=os.environ.get("HF_HOME") and str(Path(os.environ["HF_HOME"]) / "hub") or None)
    print(f"Model siap: {path}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="engines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("check")
    i = sub.add_parser("install")
    i.add_argument("kind", choices=["cpu", "cuda"])
    i.add_argument("--diarize", action="store_true")
    w = sub.add_parser("warmup")
    w.add_argument("model", nargs="?", default="large-v3")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(status()))
        return 0
    if a.cmd == "check":
        r = check()
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    if a.cmd == "install":
        return install(a.kind, a.diarize)
    return warmup(a.model)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
