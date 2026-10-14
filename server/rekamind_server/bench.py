"""Run on YOUR machine against YOUR recordings; nothing is uploaded anywhere.

    python -m rekamind_server.bench rapat.wav --ref rapat.txt --model large-v3 --device auto

Prints one JSON object: speed (real-time factor), peak memory, and -- when a
reference transcript is given -- word error rate. Send back only that JSON."""

import argparse
import json
import platform
import re
import sys
import time
from pathlib import Path

from . import resource_probe


def normalize(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate = word-level edit distance / reference length."""
    r, h = normalize(reference), normalize(hypothesis)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def audio_seconds(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="WAV file (16-bit PCM)")
    ap.add_argument("--ref", type=Path, help="plain-text reference transcript, for WER")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute-type", default="auto")
    ap.add_argument("--language", default="id")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--out", type=Path, help="also write the hypothesis transcript here")
    args = ap.parse_args(argv)

    from .engines.whisper import FasterWhisperTranscriber, pick_device_and_compute

    device, compute = pick_device_and_compute(args.device, args.compute_type)
    asr = FasterWhisperTranscriber(args.model, args.device, args.compute_type, args.glossary)
    t0 = time.perf_counter()
    asr._load()
    load_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    segs = asr.transcribe(args.audio, args.language)
    run_s = time.perf_counter() - t1
    hyp = " ".join(s.text for s in segs)
    dur = audio_seconds(args.audio)

    result = {
        "model": args.model, "device": device, "compute_type": compute,
        "platform": platform.platform(), "audio_seconds": round(dur, 1),
        "model_load_seconds": round(load_s, 1), "transcribe_seconds": round(run_s, 1),
        "realtime_factor": round(run_s / dur, 3) if dur else None,  # <1 means faster than real time
        "peak_rss_mb": resource_probe.peak_rss_mb(),
        "segments": len(segs), "words": len(normalize(hyp)),
    }
    if args.ref:
        result["wer"] = round(wer(args.ref.read_text(encoding="utf-8"), hyp), 4)
    if args.out:
        args.out.write_text("\n".join(f"[{s.start_ms/1000:7.1f}] {s.text}" for s in segs), encoding="utf-8")
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
