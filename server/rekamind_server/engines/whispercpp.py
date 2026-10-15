"""GPU transcription through whisper.cpp built with Vulkan: AMD (Radeon 680M/780M/860M integrated and discrete),
and any other GPU with a Vulkan driver. The program (`whisper-cli`) is built by this project's CI and installed into
the engine pack; it is run as a separate process, so a driver crash cannot take the backend down.

Notes that matter on real hardware:
- whisper.cpp does its own 30 s windowing, beam search and timestamping, so segments are fine-grained and long
  recordings need no splitting here.
- On a laptop with an integrated and a discrete GPU, `device` (whisper-cli `-dev`) picks which Vulkan device runs it.
  The device actually used is read from the program's log and kept in `active_device`.
- If no Vulkan device initialises, whisper.cpp itself falls back to the CPU; that is reported in `active_device`
  as "CPU" and logged as a warning, so a silently slow run is at least visible.
- The glossary / initial prompt is not applied.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .. import engine_assets
from .base import AsrSegment

log = logging.getLogger(__name__)

# "ggml_vulkan: 0 = AMD Radeon(TM) 860M Graphics (AMD proprietary driver) | uma: 1 | fp16: 1 | ..."
# The name may itself contain parentheses ("Radeon(TM)", "Intel(R)"); only a *space* + "(driver text)" before "|" is cut off.
_VK_DEVICE = re.compile(r"ggml_vulkan:\s*(\d+)\s*=\s*(.+?)(?:\s+\([^()]*\))?\s*(?:\||$)", re.IGNORECASE | re.MULTILINE)
# whisper.cpp prints these for sound it recognised but that is not speech
_NOT_SPEECH = re.compile(r"^\s*[\[(<*♪].*[\])>*♪]\s*$")


def parse_devices(stderr: str) -> list[str]:
    seen: dict[str, str] = {}
    for m in _VK_DEVICE.finditer(stderr):
        seen.setdefault(m.group(1), m.group(2).strip())
    return list(seen.values())


def parse_segments(doc: dict) -> list[AsrSegment]:
    out: list[AsrSegment] = []
    for s in doc.get("transcription", []):
        text = (s.get("text") or "").strip()
        if not text or _NOT_SPEECH.match(text):
            continue
        off = s.get("offsets") or {}
        a, b = int(off.get("from", 0)), int(off.get("to", 0))
        out.append(AsrSegment(a, max(b, a + 1), text))
    return out


class WhisperCppTranscriber:
    def __init__(self, pack: Path, model: str = "large-v3", quant: str = "q5_0", device: int = 0, threads: int = 0):
        self._pack, self._model, self._quant = pack, model, quant
        self._device, self._threads = device, threads
        self._lock = threading.Lock()
        self.active_device = ""

    def _command(self, exe: Path, model: Path, wav: Path, language: str, prefix: Path) -> list[str]:
        cmd = [str(exe), "-m", str(model), "-f", str(wav), "-l", language.lower(), "-oj", "-of", str(prefix),
               "-dev", str(self._device), "-sns"]
        if self._threads > 0:
            cmd += ["-t", str(self._threads)]
        return cmd

    def transcribe(self, wav: Path, language: str) -> list[AsrSegment]:
        exe = engine_assets.find_binary(self._pack)
        if exe is None:
            raise RuntimeError("Mesin GPU (Vulkan) belum dipasang. Pasang dari Pengaturan → Mesin transkripsi.")
        with self._lock:  # one process at a time: two big models would fight over the iGPU's shared memory
            model = engine_assets.ensure_model(self._model, self._quant, log=lambda m: log.info(m))
            with tempfile.TemporaryDirectory() as d:
                prefix = Path(d) / "out"
                flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window
                proc = subprocess.run(  # noqa: S603 - our own program, arguments are paths/ints we built
                    self._command(exe, model, Path(wav), language, prefix),
                    capture_output=True, text=True, encoding="utf-8", errors="replace", **flags)
                if proc.returncode != 0:
                    tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
                    raise RuntimeError(f"whisper-cli gagal (kode {proc.returncode}): {tail}")
                result = prefix.with_suffix(".json")
                if not result.is_file():
                    raise RuntimeError("whisper-cli selesai tetapi tidak menulis hasil JSON.")
                doc = json.loads(result.read_text("utf-8"))
        devices = parse_devices(proc.stderr or "")
        if devices:
            self.active_device = devices[min(self._device, len(devices) - 1)]
            log.info("whisper.cpp memakai GPU Vulkan: %s", self.active_device)
        else:
            self.active_device = "CPU"
            log.warning("whisper.cpp tidak menemukan perangkat Vulkan; berjalan di CPU (lambat)")
        return parse_segments(doc)

    def release(self) -> None:  # nothing stays loaded between runs: each transcription is its own process
        return None
