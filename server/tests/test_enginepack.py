import json
import sys

import pytest

from rekamind_server import enginepack


def test_status_of_an_empty_pack_is_not_installed(tmp_path):
    s = enginepack.status(tmp_path / "nope")
    assert s["kind"] is None and s["pack_dir"].endswith("nope")


def test_activate_puts_an_existing_pack_on_the_path_once_and_ignores_a_missing_one(tmp_path):
    before = list(sys.path)
    try:
        enginepack.activate(tmp_path / "missing")
        assert sys.path == before
        enginepack.activate(tmp_path)
        enginepack.activate(tmp_path)
        assert sys.path.count(str(tmp_path)) == 1 and sys.path[-1] == str(tmp_path), "appended, so it never shadows the backend's own libraries"
    finally:
        sys.path[:] = before


def test_status_reads_the_marker_written_by_a_finished_install(tmp_path):
    (tmp_path / "installed.json").write_text(json.dumps({"kind": "cuda", "diarize": True}))
    assert enginepack.status(tmp_path)["kind"] == "cuda"
    (tmp_path / "installed.json").write_text("{broken")
    assert enginepack.status(tmp_path)["kind"] is None  # a corrupt marker never crashes the app


def test_pip_arguments_differ_by_hardware_and_never_touch_the_system_site(tmp_path):
    cpu = enginepack.pip_args("cpu", tmp_path, False)
    cuda = enginepack.pip_args("cuda", tmp_path, True, ["numpy==2.5.4"])
    assert "--no-warn-conflicts" in cpu  # no alarming conflict noise from the frozen app's own metadata
    assert "--target" in cpu and str(tmp_path) in cpu and "--only-binary=:all:" in cpu
    assert not any(a.startswith("nvidia") for a in cpu)
    assert "--find-links" not in cpu  # speech-only install never touches the torch index
    assert "https://download.pytorch.org/whl/cu126/torch/" in cuda  # diarization needs torch, from the matching wheel page
    assert "--extra-index-url" not in cuda  # that index would route nvidia-* to the slow pypi.nvidia.com
    assert "https://download.pytorch.org/whl/cpu/torch/" in enginepack.pip_args("cpu", tmp_path, True)
    assert any(a.startswith("nvidia-cudnn") for a in cuda) and any(a.startswith("pyannote") for a in cuda)
    assert "numpy==2.5.4" in cuda  # keeps the pack consistent with what the frozen backend carries
    assert not any(a.startswith("pyannote") for a in cpu)
    with pytest.raises(ValueError):
        enginepack.pip_args("rocm", tmp_path, False)


def test_check_reports_a_missing_engine_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ctranslate2", None)  # import -> ImportError
    r = enginepack.check(tmp_path)
    assert r["ok"] is False and "ctranslate2" in r["error"]


def test_the_pack_pins_av_below_17_and_the_backend_bundles_the_same_range():
    assert "av>=12,<17" in enginepack.PACKAGES["asr"]
    import re
    from pathlib import Path

    py = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert re.search(r'"av>=12,<17"', py), "the frozen backend must carry an av the pack also accepts"


def test_selftest_runs_the_distlib_launcher_lookup_that_failed_in_the_frozen_windows_build():
    r = enginepack.selftest()
    assert r["ok"] is True, r
    assert enginepack.fix_distlib_for_frozen() is None  # idempotent


def test_install_applies_the_frozen_distlib_fix_before_running_pip(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(enginepack, "fix_distlib_for_frozen", lambda: calls.append("fix"))
    import pip._internal.cli.main as pipmain

    monkeypatch.setattr(pipmain, "main", lambda args: calls.append("pip") or 0)
    assert enginepack.install("cpu", pack=tmp_path) == 0
    assert calls == ["fix", "pip"]
