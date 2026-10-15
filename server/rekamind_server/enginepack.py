"""The optional "engine pack": faster-whisper (+ pyannote) installed *next to* the frozen backend.

The desktop installer ships a small backend (API, queue, SQLite, audio decoding). The machine-learning
libraries are several GB and depend on the hardware (CPU or NVIDIA), so they are installed on demand
into a user folder and put on `sys.path` before the engines are imported. This module is also usable
from a normal Python install (`python -m rekamind_server.enginepack status`).
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import threading
from pathlib import Path

TORCH_INDEX = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cuda": "https://download.pytorch.org/whl/cu126",
    # OpenVINO exports Whisper through torch/transformers once; the CPU wheel is all it needs.
    "openvino": "https://download.pytorch.org/whl/cpu",
    "vulkan": "https://download.pytorch.org/whl/cpu",  # only used when speaker separation (pyannote) is added
}
KINDS = ("cpu", "cuda", "openvino", "vulkan")
# Pins follow the v1 README (torch 2.13 / cu126); ctranslate2 comes in through faster-whisper.
PACKAGES = {
    # av<17: faster-whisper 1.2.x calls av.open(..., metadata_errors=...), which av 17+ rejects
    # (measured: every transcription failed with a TypeError on a freshly installed pack).
    "asr": ["faster-whisper>=1.0", "soundfile>=0.12", "av>=12,<17"],
    "diarize": ["pyannote.audio>=4.0", "soundfile>=0.12"],
    # faster-whisper on NVIDIA needs the CUDA 12 runtime libraries next to it.
    "cuda_runtime": ["nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"],
    # Intel GPU / iGPU (and Intel CPU) through OpenVINO: the optimum-intel path validated in v1 on a Core Ultra 7 155H.
    "openvino": ["openvino>=2025.0", "optimum-intel[openvino]>=1.20", "transformers>=4.45", "torch", "soundfile>=0.12", "av>=12,<17"],
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
        # At the END: whatever the frozen backend (or the venv) already carries wins, so the pack can add
        # libraries but never shadow the backend's own sqlalchemy/alembic/numpy/av with other versions.
        sys.path.append(p)
    if sys.platform == "win32" and pack.is_dir():
        # Native DLLs (torch, ctranslate2, cuDNN) are no longer found through PATH on Python 3.8+.
        for d in [pack / "torch" / "lib", pack / "ctranslate2", pack / "openvino" / "libs", *pack.glob("nvidia/*/bin")]:
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
        "asr": _has("faster_whisper")
        or (meta.get("kind") == "openvino" and _has("openvino") and _has("optimum"))
        or (meta.get("kind") == "vulkan" and _vulkan_installed(pack)),
        "diarize": _has("pyannote.audio") or _has("pyannote"),
        "kind": meta.get("kind"),  # "cpu" | "cuda" | "openvino" | None
        "gpus": detect_gpus(),
        "build": __import__("rekamind_server").build_id(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


_VENDORS = {"0x8086": "intel", "0x10de": "nvidia", "0x1002": "amd"}


GPU_CACHE_SECONDS = 24 * 3600


def _gpu_cache_file() -> Path:
    return Path(os.environ.get("REKAMIND_DATA_DIR") or Path.home() / ".rekamind") / "gpus.json"


@functools.lru_cache(maxsize=1)
def detect_gpus() -> list[dict]:
    """`_detect_gpus` with a one-day file cache: the desktop app asks for `engines status` in a fresh process each
    time, and a PowerShell call on every refresh would slow the engine panel for everybody (also NVIDIA/CPU users)."""
    import time

    f = _gpu_cache_file()
    try:
        c = json.loads(f.read_text("utf-8"))
        if c.get("platform") == sys.platform and time.time() - float(c.get("at", 0)) < GPU_CACHE_SECONDS:
            return list(c["gpus"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    gpus = _detect_gpus()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"platform": sys.platform, "at": time.time(), "gpus": gpus}), "utf-8")
    except OSError:
        pass
    return gpus


def _detect_gpus() -> list[dict]:
    """Which GPUs does this computer have? ([{"vendor": "intel|nvidia|amd|other", "name": str}]). Used only to
    recommend an engine kind: it imports nothing heavy and never raises."""
    out: list[dict] = []
    try:
        if sys.platform == "win32":
            import subprocess

            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",  # noqa: S607 - fixed command
                   "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=0x08000000)  # noqa: S603
            names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        elif sys.platform.startswith("linux"):
            names = []
            for dev in sorted(Path("/sys/class/drm").glob("card[0-9]*/device")):
                vendor = (dev / "vendor").read_text().strip() if (dev / "vendor").is_file() else ""
                if vendor in _VENDORS:
                    out.append({"vendor": _VENDORS[vendor], "name": f"{_VENDORS[vendor]} {vendor}"})
            return out
        else:
            return out
        for n in names:
            low = n.lower()
            vendor = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low) else "intel" if "intel" in low else "other"
            out.append({"vendor": vendor, "name": n})
    except Exception:  # noqa: BLE001 - a recommendation must never break "status"
        return out
    return out


def _vulkan_installed(pack: Path) -> bool:
    from . import engine_assets

    return engine_assets.find_binary(pack) is not None


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


def installed_kind(pack: Path | None = None) -> str | None:
    """"cpu" | "cuda" | "openvino" | None: reads the marker only (no imports, no GPU probing)."""
    return _kind(pack)


def _kind(pack: Path | None) -> str | None:
    marker = (pack or default_pack_dir()) / "installed.json"
    try:
        return json.loads(marker.read_text("utf-8")).get("kind")
    except (OSError, ValueError):
        return None


def _check_openvino(out: dict) -> dict:
    """Import the OpenVINO stack and report which devices it sees (an Intel iGPU shows up as "GPU")."""
    try:
        import openvino as ov
        import optimum.intel.openvino  # noqa: F401 - the import is the test
        import transformers

        devices = list(ov.Core().available_devices)
        out.update(ok=True, openvino=ov.__version__, transformers=transformers.__version__,
                   ov_devices=devices, intel_gpu=any(d.startswith("GPU") for d in devices))
    except Exception as e:  # noqa: BLE001 - report, never crash the caller
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _check_vulkan(out: dict, pack: Path | None) -> dict:
    """The program must start (a missing DLL or a blocked executable shows up here), and, when a model is already
    cached, a one-second run reports which Vulkan device it would use (a Radeon iGPU shows as e.g. "AMD Radeon(TM) 860M")."""
    import struct
    import subprocess
    import tempfile
    import wave

    from . import engine_assets
    from .engines.whispercpp import parse_devices

    pack = pack or default_pack_dir()
    exe = engine_assets.find_binary(pack)
    if exe is None:
        out["error"] = "whisper-cli tidak ditemukan di engine-pack (pasang ulang mesin GPU Vulkan)."
        return out
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        r = subprocess.run([str(exe), "-h"], capture_output=True, text=True, timeout=30, **flags)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = f"whisper-cli tidak bisa dijalankan: {type(e).__name__}: {e}"
        return out
    out.update(ok=True, whispercpp_binary=str(exe), vulkan_devices=[], gpu=False, model_cached=None)
    info = exe.parent / "BUILD_INFO.json"
    try:
        out["whispercpp"] = json.loads(info.read_text("utf-8")).get("whispercpp_tag")
    except (OSError, ValueError):
        pass
    if r.returncode not in (0, 1):  # -h exits 0 or 1 depending on the build; anything else is a crash
        out.update(ok=False, error=f"whisper-cli -h berhenti dengan kode {r.returncode}: {(r.stderr or '')[-300:]}")
        return out
    model = None
    for name in ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"):
        model = model or engine_assets.existing_model(name, "q5_0") or engine_assets.existing_model(name, "")
    if model is None:
        out["note"] = "Belum ada model terunduh: perangkat GPU baru bisa dipastikan setelah model diunduh (Unduh model)."
        return out
    out["model_cached"] = model.name
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "probe.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(struct.pack("<h", 0) * 16000)
        try:
            p = subprocess.run([str(exe), "-m", str(model), "-f", str(wav), "-l", "id", "-np"],  # noqa: S603
                               capture_output=True, text=True, timeout=300, **flags)
            out["vulkan_devices"] = parse_devices(p.stderr or "")
            out["gpu"] = bool(out["vulkan_devices"])
            if p.returncode != 0:
                out.update(ok=False, error=f"Uji transkripsi gagal (kode {p.returncode}): {(p.stderr or '')[-300:]}")
        except (OSError, subprocess.SubprocessError) as e:
            out.update(ok=False, error=f"Uji transkripsi gagal: {type(e).__name__}: {e}")
    return out


def check(pack: Path | None = None) -> dict:
    """Actually import the engines (unlike `status`) so a broken install is caught here, not mid-meeting."""
    activate(pack)
    out: dict = {"ok": False, "cuda_devices": 0, "error": None}
    if _kind(pack) == "openvino":
        return _check_openvino(out)
    if _kind(pack) == "vulkan":
        return _check_vulkan(out, pack)
    try:
        import ctranslate2
        import faster_whisper

        out["ctranslate2"] = ctranslate2.__version__
        out["faster_whisper"] = faster_whisper.__version__
        out["cuda_devices"] = int(ctranslate2.get_cuda_device_count())
        # Importing is not enough: a mismatched av broke audio decoding only when a file was opened.
        import struct
        import tempfile
        import wave

        from faster_whisper.audio import decode_audio

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "probe.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(struct.pack("<h", 100) * 3200)
            out["decoded_samples"] = int(len(decode_audio(str(path))))
        out["ok"] = out["decoded_samples"] > 0
    except Exception as e:  # noqa: BLE001 - report, never crash the caller
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def pip_args(kind: str, pack: Path, with_diarize: bool, pins: list[str] | None = None) -> list[str]:
    if kind not in KINDS:
        raise ValueError("kind harus 'cpu', 'cuda' atau 'openvino'")
    # The OpenVINO path does not use faster-whisper; the Vulkan path is a native program and installs no Python
    # package for transcription at all (only speaker separation, when asked for, is pip-installed).
    pkgs = [] if kind == "vulkan" else list(PACKAGES["openvino"] if kind == "openvino" else PACKAGES["asr"])
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
            *(["--extra-index-url", TORCH_INDEX[kind]] if (with_diarize or kind == "openvino") else []),
            *pkgs, *(pins or [])]


_ML_STDLIB = ("pickletools", "cProfile", "pstats", "unittest.mock", "xml.etree.ElementTree", "mmap", "unicodedata", "venv", "sqlite3", "ctypes.util", "multiprocessing.shared_memory", "concurrent.futures.process", "asyncio", "logging.handlers", "zoneinfo", "tarfile", "zipfile", "curses" if False else "decimal")


def fix_distlib_for_frozen() -> None:
    """pip (running inside the PyInstaller backend) asks distlib for package resources, and distlib only
    knows the loaders of a normal interpreter: on Windows that raised `Unable to locate finder for
    'pip._vendor.distlib'` and no engine could be installed. Teach it that the frozen loader reads files
    from disk like any other (the data files are collected next to the executable)."""
    from pip._vendor import distlib
    from pip._vendor.distlib import resources

    loader = getattr(distlib, "__loader__", None)
    if loader is not None and type(loader) not in resources._finder_registry:
        resources.register_finder(loader, resources.ResourceFinder)  # takes an instance, keys on its type


def selftest(fix: bool = True) -> dict:
    """Exercise the distlib path that failed (resource lookup for the script launcher), without any network."""
    out: dict = {"ok": False, "error": None, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        if fix:
            fix_distlib_for_frozen()
        from pip._vendor.distlib.resources import finder

        # distlib's Windows script writer does exactly this to find its t64.exe launcher.
        if finder("pip._vendor.distlib").find("t64.exe") is None:
            raise FileNotFoundError("t64.exe is not bundled with pip._vendor.distlib")
        # Standard-library modules that torch / pyannote import but the backend itself never does
        # (pickletools was missing from the frozen build and broke speaker separation).
        missing = []
        for name in _ML_STDLIB:
            try:
                __import__(name)
            except Exception:  # noqa: BLE001
                missing.append(name)
        out["missing_stdlib"] = missing
        out["ok"] = not missing
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        try:
            from pip._vendor.distlib import resources

            m = sys.modules.get("pip._vendor.distlib")
            out["loader"] = repr(type(getattr(m, "__loader__", None)))
            out["registered"] = [repr(k) for k in resources._finder_registry]  # noqa: SLF001
        except Exception as inner:  # noqa: BLE001
            out["diagnostics_error"] = str(inner)
    return out


# ---- visibility and robustness of a long pip download ---------------------------------------------------------
_SECRET_IN_URL = re.compile(r"(://)[^/@\s]+@")


def mask_secrets(text: str) -> str:
    """`https://user:pass@host` -> `https://***@host`."""
    return _SECRET_IN_URL.sub(r"\1***@", text)


def pip_version() -> tuple[int, int]:
    try:
        from pip import __version__

        major, minor = (int(x) for x in __version__.split(".")[:2])
        return major, minor
    except Exception:  # noqa: BLE001 - unknown pip: behave conservatively
        return (0, 0)


def tune_pip_args(args: list[str], version: tuple[int, int]) -> list[str]:
    """Longer timeouts/retries on every pip; on pip >= 25.1 also resumable downloads and machine-readable progress
    (`--progress-bar raw`), which `ProgressReporter` turns into one line every few seconds. An older pip keeps
    the original arguments exactly (an unknown option would make the whole install fail)."""
    out = list(args)
    out[1:1] = ["--timeout", "60", "--retries", "10"]  # args[0] is the "install" command
    if version >= (25, 1):
        i = out.index("--progress-bar")
        out[i + 1] = "raw"
        out[1:1] = ["--resume-retries", "5"]
    return out


def force_utf8_streams() -> None:
    """Write UTF-8 whatever the console code page is, and never raise on an unencodable character. The desktop app
    reads this output as UTF-8; cp1252 bytes (e.g. the ellipsis) used to make it stop reading and close the pipe."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001, S110 - not a text stream (e.g. a test double): nothing to do
            pass


class SafeStream:
    """A write-through wrapper that swallows `OSError` (a broken pipe is `Errno 22` on Windows). pip treats an OSError
    from its own output as an install failure, so a reader that went away must not abort a 1 GB download."""

    def __init__(self, out, keep: int = 0):
        self._out, self.broken, self._keep, self.recent = out, False, keep, ""

    def write(self, s: str) -> int:
        if self._keep:  # remember the tail so the caller can recognise a known pip failure
            self.recent = (self.recent + s)[-self._keep:]
        if not self.broken:
            try:
                self._out.write(s)
            except (OSError, ValueError):
                self.broken = True
        return len(s)

    def flush(self) -> None:
        if not self.broken:
            try:
                self._out.flush()
            except (OSError, ValueError):
                self.broken = True

    def __getattr__(self, name):
        return getattr(self._out, name)


class ProgressReporter:
    """Wraps stdout while pip runs: turns pip's "Progress N of M" lines into a readable line every few seconds
    (MB, percent, speed) and warns when a download makes no progress. A silent 700 MB download over a slow link is
    indistinguishable from a hang, which is what users saw."""

    def __init__(self, out, every: float = 5.0, stall: float = 60.0, clock=None):
        import time

        self._out, self._every, self._stall = SafeStream(out, keep=6000), every, stall
        self._clock = clock or time.monotonic
        self._last_print = self._last_change = self._last_warn = self._clock()
        self._last_cur, self._last_print_cur, self._total, self._active = 0, 0, 0, False

    def write(self, s: str) -> int:
        for line in s.splitlines(keepends=True):
            if line.startswith("Progress "):
                self._progress(line)
            else:
                self._out.write(line)
        return len(s)

    def _progress(self, line: str) -> None:
        try:
            _, cur, _, tot = line.split()
            cur, tot = int(cur), int(tot)
        except ValueError:
            return
        now = self._clock()
        if cur < self._last_cur:  # a new file started
            self._last_print, self._last_print_cur, self._last_warn = now, 0, now
        if cur > self._last_cur:
            self._last_change = now
        self._last_cur, self._total, self._active = cur, tot, cur < tot
        if cur >= tot or now - self._last_print >= self._every:
            dt = max(now - self._last_print, 1e-6)
            speed = (cur - self._last_print_cur) / dt / 1e6
            of_total = f" / {tot / 1e6:,.0f} MB ({cur * 100 // tot}%)" if tot else " MB"
            self._out.write(f"  ... {cur / 1e6:,.0f}{of_total}, {speed:.2f} MB/s\n")
            self._last_print, self._last_print_cur = now, cur

    @property
    def recent(self) -> str:
        return self._out.recent

    def check_stall(self) -> bool:
        """Called periodically from a watchdog thread; True (and a warning line) when a download has stood still."""
        now = self._clock()
        if self._active and now - self._last_change >= self._stall and now - self._last_warn >= self._stall:
            self._last_warn = now
            self._out.write(f"  ! Tidak ada kemajuan unduhan selama {int(now - self._last_change)} dtk "
                            f"({self._last_cur / 1e6:,.0f} dari {self._total / 1e6:,.0f} MB). Jaringan ke server paket lambat "
                            "atau terputus; pip masih mencoba. Lihat docs/INSTALL.md, bagian pemasangan lambat.\n")
            return True
        return False

    def flush(self) -> None:
        self._out.flush()

    def __getattr__(self, name):
        return getattr(self._out, name)


def describe_environment(kind: str, log=print, probe: bool = True, with_diarize: bool = False) -> None:
    """What a slow or failing install needs to be diagnosed: pip/Python, which package sources and proxies apply
    (credentials masked), and how reachable the package hosts are from this machine right now."""
    frozen = " (aplikasi terpasang)" if getattr(sys, "frozen", False) else ""
    from . import __version__, build_id

    log(f"Rekamind {__version__}, build {build_id()}")
    log(f"Diagnostik: pip {'.'.join(map(str, pip_version()))}, Python {sys.version_info.major}.{sys.version_info.minor}{frozen}, {sys.platform}")
    envs = [f"{k}={mask_secrets(os.environ[k])}" for k in (
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PIP_CONFIG_FILE", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "http_proxy", "https_proxy") if os.environ.get(k)]
    log("Variabel lingkungan pip/proxy: " + ("; ".join(envs) if envs else "tidak ada (bawaan: pypi.org)"))
    cfgs = [str(p) for p in (Path(os.environ.get("APPDATA", "")) / "pip" / "pip.ini", Path.home() / ".pip" / "pip.conf",
                             Path.home() / ".config" / "pip" / "pip.conf") if p.is_file()]
    if cfgs:
        log("Berkas konfigurasi pip: " + ", ".join(cfgs))
    if not probe:
        return
    import socket
    import ssl
    import time

    hosts = ["pypi.org", "files.pythonhosted.org"] + (["download.pytorch.org"] if kind == "openvino" or with_diarize else [])
    results: dict[str, str] = {}

    def one(host: str) -> None:
        try:
            t0 = time.monotonic()
            ip = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)[0][4][0]
            t1 = time.monotonic()
            with socket.create_connection((host, 443), timeout=6) as s, ssl.create_default_context().wrap_socket(s, server_hostname=host):
                results[host] = f"{ip}, DNS {t1 - t0:.2f} dtk, TLS {time.monotonic() - t1:.2f} dtk"
        except Exception as e:  # noqa: BLE001 - diagnostics only
            results[host] = f"GAGAL ({type(e).__name__}: {e})"

    threads = [threading.Thread(target=one, args=(h,), daemon=True) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(8)
    for h in hosts:
        log(f"  {h}: {results.get(h, 'tidak menjawab dalam 8 dtk')}")


def install(kind: str, with_diarize: bool = False, pack: Path | None = None) -> int:
    """Run pip *inside this interpreter* (works from the frozen backend too). Output goes to stdout."""
    pack = pack or default_pack_dir()
    pack.mkdir(parents=True, exist_ok=True)
    print(f"Lokasi pack: {pack}", flush=True)  # the CLI and the desktop app may use different folders
    fix_distlib_for_frozen()  # same fix selftest applies; without it pip dies in distlib when frozen
    from pip._internal.cli.main import (
        main as pip_main,  # bundled with the frozen backend
    )

    if kind == "vulkan":
        from . import engine_assets

        try:
            exe = engine_assets.install_program(pack, log=lambda m: print(m, flush=True))
            print(f"whisper-cli terpasang: {exe}", flush=True)
        except engine_assets.AssetError as e:
            print(f"GAGAL: {e}", flush=True)
            return 1
        if not with_diarize:  # nothing for pip to do
            (pack / "installed.json").write_text(json.dumps({"kind": kind, "diarize": False}), "utf-8")
            return 0
    describe_environment(kind, log=lambda m: print(m, flush=True), with_diarize=with_diarize)
    pins = _bundled_pins()
    code, text = _run_pip(kind, pack, with_diarize, pip_main, pins)
    if code != 0 and pins and "ResolutionImpossible" in text:
        # The pack's libraries must agree with the numpy/av inside the frozen backend; when they cannot (a library
        # releases a stricter cap), one retry without those pins still gives a usable pack, because the app's own
        # copies win at run time. `check` ("Uji mesin") verifies the result.
        print("Aviso: pip tidak menemukan kombinasi paket yang cocok dengan versi numpy/av bawaan aplikasi; mencoba sekali lagi "
              "tanpa mengikat versi itu (pustaka bawaan aplikasi tetap dipakai saat berjalan).", flush=True)
        code, _ = _run_pip(kind, pack, with_diarize, pip_main, [])
    if code == 0:
        (pack / "installed.json").write_text(json.dumps({"kind": kind, "diarize": with_diarize}), "utf-8")
    return code


def _run_pip(kind: str, pack: Path, with_diarize: bool, pip_main, pins: list[str]) -> tuple[int, str]:
    """One pip run with observable progress and a shielded output; returns (exit code, tail of its output)."""
    args = tune_pip_args(pip_args(kind, pack, with_diarize, pins), pip_version())
    reporter = ProgressReporter(sys.stdout)
    err = SafeStream(sys.stderr, keep=6000)
    stop = threading.Event()

    def watchdog() -> None:
        while not stop.wait(15):
            reporter.check_stall()

    threading.Thread(target=watchdog, daemon=True).start()
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = reporter, err
    try:
        code = int(pip_main(args) or 0)
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        stop.set()
    return code, reporter.recent + err.recent


def warmup(model: str, pack: Path | None = None) -> int:
    """Download the Whisper weights now (instead of at the first meeting). Needs the pack installed."""
    activate(pack)
    # Hugging Face: use the user's token when there is one (faster, higher limits) and silence the Windows symlink
    # warning (it only means the cache uses more disk space), which otherwise buries the real progress in the log.
    if os.environ.get("REKAMIND_HF_TOKEN"):
        os.environ.setdefault("HF_TOKEN", os.environ["REKAMIND_HF_TOKEN"])
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if _kind(pack) == "vulkan":
        from . import engine_assets

        quant = os.environ.get("REKAMIND_WHISPERCPP_QUANT", "q5_0")
        path = engine_assets.ensure_model(model, quant, log=lambda m: print(m, flush=True))
        print(f"Model siap: {path}", flush=True)
        return 0
    if _kind(pack) == "openvino":
        from .engines.openvino import prepare_model

        print(f"Mengonversi model {model} ke OpenVINO (sekali saja; beberapa menit dan beberapa GB memori) ...", flush=True)
        path = prepare_model(model, log=lambda m: print(m, flush=True))
        print(f"Model siap: {path}", flush=True)
        return 0
    import threading

    from faster_whisper.utils import download_model

    if os.environ.get("REKAMIND_HF_TOKEN"):
        os.environ.setdefault("HF_TOKEN", os.environ["REKAMIND_HF_TOKEN"])
    cache = os.environ.get("HF_HOME") and str(Path(os.environ["HF_HOME"]) / "hub") or None
    print(f"Mengunduh model {model} (bisa beberapa GB; progres tampil tiap beberapa detik) ...", flush=True)
    done = threading.Event()

    def report() -> None:
        # huggingface_hub's own progress bar is silent when not attached to a terminal, which made a
        # 6-minute download look like a hang.
        root = Path(cache) if cache else Path.home() / ".cache" / "huggingface" / "hub"
        while not done.wait(4):
            try:
                size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                print(f"  ... {size / 1e6:,.0f} MB terunduh", flush=True)
            except OSError:
                pass

    threading.Thread(target=report, daemon=True).start()
    try:
        path = download_model(model, cache_dir=cache)
    finally:
        done.set()
    print(f"Model siap: {path}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    force_utf8_streams()
    try:
        return _main(argv)
    finally:
        # A reader that went away makes the interpreter's final flush fail and replaces the exit code with 120,
        # even when the command succeeded. Make the final flush harmless.
        for name in ("stdout", "stderr"):
            try:
                getattr(sys, name).flush()
            except (OSError, ValueError, AttributeError):
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="engines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("check")
    st = sub.add_parser("selftest")
    st.add_argument("--no-fix", action="store_true", help="skip the frozen-loader fix (reproduces the Windows failure)")
    i = sub.add_parser("install")
    i.add_argument("kind", choices=list(KINDS))
    i.add_argument("--diarize", action="store_true")
    w = sub.add_parser("warmup")
    w.add_argument("model", nargs="?", default="large-v3")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(status()))
        return 0
    if a.cmd == "selftest":
        r = selftest(not a.no_fix)
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    if a.cmd == "check":
        r = check()
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    if a.cmd == "install":
        return install(a.kind, a.diarize)
    return warmup(a.model)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
