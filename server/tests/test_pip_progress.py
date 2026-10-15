"""Long engine installs must be observable and robust, without changing what CPU/NVIDIA installs ask pip to do."""
import io
import json

from rekamind_server import enginepack
from rekamind_server.enginepack import (
    ProgressReporter,
    describe_environment,
    mask_secrets,
    tune_pip_args,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_credentials_in_urls_are_masked():
    assert mask_secrets("https://user:s3cret@mirror.example/simple") == "https://***@mirror.example/simple"
    assert mask_secrets("http://proxy:8080") == "http://proxy:8080"


BASE = ["install", "--target", "/p", "--upgrade", "--only-binary=:all:", "--progress-bar", "off", "faster-whisper>=1.0"]


def test_old_pip_keeps_the_original_arguments_plus_safe_timeouts():
    a = tune_pip_args(BASE, (24, 0))
    assert a[0] == "install" and a[1:5] == ["--timeout", "60", "--retries", "10"]
    assert "--resume-retries" not in a and a[a.index("--progress-bar") + 1] == "off"  # an unknown option would break the install
    assert a[5:] == BASE[1:]


def test_new_pip_gets_resumable_downloads_and_raw_progress():
    a = tune_pip_args(BASE, (25, 1))
    assert "--resume-retries" in a and a[a.index("--progress-bar") + 1] == "raw"
    assert a[0] == "install" and "faster-whisper>=1.0" in a and "--only-binary=:all:" in a  # nothing else changed
    assert tune_pip_args(BASE, (26, 2))[tune_pip_args(BASE, (26, 2)).index("--resume-retries") + 1] == "5"


def test_progress_lines_are_throttled_and_readable():
    out, clock = io.StringIO(), Clock()
    r = ProgressReporter(out, every=5.0, clock=clock)
    r.write("Collecting nvidia-cudnn-cu12\n")
    r.write("Progress 0 of 743000000\n")
    for i in range(1, 6):  # a burst within one second prints nothing
        clock.t += 0.2
        r.write(f"Progress {i * 100_000} of 743000000\n")
    assert out.getvalue() == "Collecting nvidia-cudnn-cu12\n"
    clock.t += 5.0
    r.write("Progress 10500000 of 743000000\n")
    line = out.getvalue().splitlines()[-1]
    assert line.startswith("  ... 10 / 743 MB (1%)") and line.endswith("MB/s")
    clock.t += 0.1
    r.write("Progress 743000000 of 743000000\n")  # completion always prints
    assert out.getvalue().splitlines()[-1].startswith("  ... 743 / 743 MB (100%)")


def test_a_stalled_download_warns_once_per_interval_and_never_when_idle():
    out, clock = io.StringIO(), Clock()
    r = ProgressReporter(out, stall=60.0, clock=clock)
    assert r.check_stall() is False  # nothing downloading
    r.write("Progress 1000000 of 500000000\n")
    clock.t += 30
    assert r.check_stall() is False
    clock.t += 31
    assert r.check_stall() is True and "Tidak ada kemajuan unduhan selama 61 dtk" in out.getvalue()
    assert r.check_stall() is False  # not again immediately
    clock.t += 61
    r.write("Progress 2000000 of 500000000\n")  # moving again
    clock.t += 30
    assert r.check_stall() is False
    r.write("Progress 500000000 of 500000000\n")
    clock.t += 500
    assert r.check_stall() is False  # finished downloads are not "stalled"


def test_unrelated_output_passes_through_untouched():
    out = io.StringIO()
    r = ProgressReporter(out)
    r.write("Successfully installed a b c\nWARNING: x\n")
    assert out.getvalue() == "Successfully installed a b c\nWARNING: x\n"
    r.write("Progress not-a-number\n")  # malformed progress is ignored, not fatal


def test_diagnostics_name_the_pip_proxy_variables_but_never_log_their_values(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pw@proxy.kantor:3128")
    monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.example/simple")
    lines: list[str] = []
    describe_environment("cuda", log=lines.append, probe=False)
    text = "\n".join(lines)
    assert "pip " in text and "PIP_INDEX_URL" in text and "HTTPS_PROXY" in text
    assert "user:pw" not in text and "proxy.kantor" not in text and "mirror.example" not in text


def test_diagnostics_probe_never_raises_without_a_network(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError("no network")))
    lines: list[str] = []
    describe_environment("cpu", log=lines.append, probe=True)
    assert any("pypi.org: GAGAL" in line for line in lines)
    assert enginepack.pip_version() >= (0, 0)


# ---- the Windows failure: a reader that went away / a code page that is not UTF-8 -----------------------------
class DeadPipe:
    """What Windows gives a writer whose reader closed the pipe: OSError [Errno 22] on write and on flush."""

    def write(self, s):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


def test_a_dead_stdout_never_aborts_the_install_output_path():
    from rekamind_server.enginepack import SafeStream

    s = SafeStream(DeadPipe())
    assert s.write("Downloading nvidia_cuda_nvrtc_cu12 (76.4 MB)\n") > 0  # pip would have failed with "Could not install packages"
    s.flush()
    assert s.broken is True
    assert s.write("more") == 4  # and stays quiet afterwards


def test_progress_reporter_survives_a_dead_pipe():
    r = ProgressReporter(DeadPipe(), clock=Clock())
    r.write("Collecting x\n")
    r.write("Progress 0 of 1000000\n")
    r.write("Progress 1000000 of 1000000\n")
    r.flush()
    assert r.check_stall() is False


def test_everything_we_print_during_an_install_is_ascii():
    """cp1252 turns the ellipsis into 0x85, which is not UTF-8 and used to make the desktop app stop reading."""
    out, clock = io.StringIO(), Clock()
    r = ProgressReporter(out, every=1.0, stall=10.0, clock=clock)
    r.write("Progress 0 of 743000000\n")
    clock.t += 2
    r.write("Progress 100000000 of 743000000\n")
    clock.t += 20
    r.check_stall()
    r.write("Progress 743000000 of 743000000\n")
    lines: list[str] = []
    describe_environment("cuda", log=lines.append, probe=False, with_diarize=True)
    text = out.getvalue() + "\n".join(lines)
    assert text and all(ord(c) < 128 for c in text), [c for c in text if ord(c) >= 128]


def test_force_utf8_makes_cp1252_consoles_emit_valid_utf8(monkeypatch):
    import io as _io

    raw = _io.BytesIO()
    cp1252 = _io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
    monkeypatch.setattr(enginepack.sys, "stdout", cp1252)
    monkeypatch.setattr(enginepack.sys, "stderr", _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252"))
    enginepack.force_utf8_streams()
    cp1252.write("  … 10 MB\n")
    assert raw.getvalue() == "  … 10 MB\n".encode()  # valid UTF-8 (E2 80 A6), not the single byte 0x85
    raw.getvalue().decode("utf-8")  # does not raise


def test_a_broken_stdout_at_exit_cannot_turn_success_into_exit_code_120(monkeypatch):
    class Broken:
        def reconfigure(self, **k):
            pass

        def write(self, s):
            return len(s)

        def flush(self):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(enginepack.sys, "stdout", Broken())
    monkeypatch.setattr(enginepack.sys, "stderr", Broken())
    monkeypatch.setattr(enginepack, "_main", lambda argv: 0)
    assert enginepack.main(["status"]) == 0
    enginepack.sys.stdout.flush()  # replaced by a harmless stream: the interpreter's own final flush now succeeds
    enginepack.sys.stderr.flush()


def test_cli_status_is_valid_utf8_even_when_python_would_use_a_legacy_code_page(tmp_path):
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "REKAMIND_DATA_DIR": str(tmp_path)}
    env.pop("PYTHONUTF8", None)
    p = subprocess.run([sys.executable, "-m", "rekamind_server.enginepack", "status"], capture_output=True, env=env, check=True)  # noqa: S603
    json.loads(p.stdout.decode("utf-8"))


# ---- "ResolutionImpossible" with the numpy pinned to the frozen backend's version (Intel/OpenVINO install) -------
def _fake_pip(monkeypatch, tmp_path, outcomes):
    """Replace pip's entry point; `outcomes` = [(exit code, text written to stderr), ...] in call order."""
    import pip._internal.cli.main as pipmain

    calls: list[list[str]] = []

    def fake_main(args):
        calls.append(list(args))
        code, text = outcomes[len(calls) - 1]
        if text:
            enginepack.sys.stderr.write(text)
        return code

    monkeypatch.setattr(pipmain, "main", fake_main)
    monkeypatch.setattr(enginepack, "describe_environment", lambda *a, **k: None)
    monkeypatch.setattr(enginepack, "_bundled_pins", lambda: ["numpy==2.5.4", "av==16.1.0"])
    return calls


def test_resolution_failure_with_bundled_pins_is_retried_once_without_them(monkeypatch, tmp_path):
    calls = _fake_pip(monkeypatch, tmp_path, [(1, "ERROR: ResolutionImpossible: for help visit https://pip.pypa.io\n"), (0, "")])
    assert enginepack.install("openvino", pack=tmp_path / "pack") == 0
    assert len(calls) == 2
    assert "numpy==2.5.4" in calls[0] and "av==16.1.0" in calls[0]
    assert "numpy==2.5.4" not in calls[1] and "av==16.1.0" not in calls[1] and "optimum-intel[openvino]>=1.20" in calls[1]
    assert json.loads((tmp_path / "pack" / "installed.json").read_text())["kind"] == "openvino"


def test_other_failures_are_not_retried_and_leave_no_marker(monkeypatch, tmp_path):
    calls = _fake_pip(monkeypatch, tmp_path, [(1, "ERROR: Could not install packages due to an OSError: network is unreachable\n")])
    assert enginepack.install("cuda", pack=tmp_path / "pack") == 1
    assert len(calls) == 1 and not (tmp_path / "pack" / "installed.json").exists()


def test_a_normal_install_runs_pip_once_with_the_pins(monkeypatch, tmp_path):
    calls = _fake_pip(monkeypatch, tmp_path, [(0, "")])
    assert enginepack.install("cpu", pack=tmp_path / "pack") == 0
    assert len(calls) == 1 and "numpy==2.5.4" in calls[0] and "faster-whisper>=1.0" in calls[0]


def test_the_backend_numpy_stays_compatible_with_the_openvino_stack():
    """nncf (pulled in by optimum-intel[openvino]) caps numpy below 2.5. The frozen backend must not ship a numpy the
    engine pack cannot be resolved against: that made the Intel install fail with ResolutionImpossible."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    line = next(entry for entry in text.splitlines() if '"numpy' in entry)
    assert "<2.5" in line, line


def test_build_is_named_in_the_diagnostics_status_and_health(client_factory=None):
    import rekamind_server

    assert rekamind_server.build_id()  # "dev" from a checkout, the commit in a built installer
    lines: list[str] = []
    describe_environment("cpu", log=lines.append, probe=False)
    assert lines[0].startswith(f"Rekamind {rekamind_server.__version__}, build ")
