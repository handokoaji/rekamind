"""Prove that every engine kind can be *resolved* by pip with the pins the app really uses.

The frozen backend bundles numpy and av; the engine pack is installed next to it and must agree with them
(`enginepack._bundled_pins`). When a library in a pack caps numpy below the bundled version, the install fails for
users with `ResolutionImpossible` (this happened to the Intel/OpenVINO pack: nncf caps numpy < 2.5). That cannot be
seen in unit tests, so CI runs the real resolver in --dry-run mode for every kind, with and without speaker separation.

    python scripts/check_engine_pack_resolves.py            # all kinds
    python scripts/check_engine_pack_resolves.py cpu openvino --no-extra-index   # subset; skip the PyTorch index
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from rekamind_server import enginepack  # noqa: E402


def command(kind: str, diarize: bool, pack: Path, no_extra_index: bool) -> list[str]:
    args = enginepack.tune_pip_args(enginepack.pip_args(kind, pack, diarize, enginepack._bundled_pins()), enginepack.pip_version())
    if no_extra_index:
        while "--extra-index-url" in args:
            i = args.index("--extra-index-url")
            del args[i:i + 2]
    # resolve only: nothing is downloaded beyond metadata and nothing is written to the pack
    return [sys.executable, "-m", "pip", *args, "--dry-run", "--ignore-installed"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kinds", nargs="*", default=list(enginepack.KINDS))
    ap.add_argument("--no-extra-index", action="store_true", help="drop the PyTorch index (e.g. where download.pytorch.org is blocked)")
    a = ap.parse_args()
    print(f"python {sys.version.split()[0]}, pip {'.'.join(map(str, enginepack.pip_version()))}, pins {enginepack._bundled_pins()}")
    failed = []
    with tempfile.TemporaryDirectory() as d:
        for kind in a.kinds:
            for diarize in (False, True):
                if kind == "vulkan" and not diarize:
                    continue  # nothing for pip to resolve
                cmd = command(kind, diarize, Path(d) / "pack", a.no_extra_index)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)  # noqa: S603
                label = f"{kind}{' + pyannote' if diarize else ''}"
                if r.returncode == 0:
                    print(f"OK    {label}")
                else:
                    failed.append(label)
                    tail = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()][-14:]
                    print(f"FAIL  {label}\n      " + "\n      ".join(tail))
    print("all engine kinds resolve" if not failed else f"cannot resolve: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
