import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("set_version", Path(__file__).resolve().parents[2] / "scripts/set_version.py")
sv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sv)


@pytest.mark.parametrize("v,py", [("0.4.0-beta.1", "0.4.0b1"), ("1.2.3", "1.2.3"), ("0.5.0-rc.2", "0.5.0rc2"), ("0.1.0-alpha.9", "0.1.0a9")])
def test_pep440(v, py):
    assert sv.pep440(v) == py


@pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "1.0.0-beta", "1.0.0-snapshot.1", "1.0.0-beta.x"])
def test_rejects_non_semver(bad):
    assert not sv.SEMVER.match(bad)


def test_repo_versions_are_in_sync():
    """Setiap berkas versi v2 harus sama dengan versi di tauri.conf.json (sumber kebenaran rilis)."""
    import json
    v = json.loads((sv.ROOT / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
    import subprocess, sys
    r = subprocess.run([sys.executable, str(sv.ROOT / "scripts/set_version.py"), "--check", v], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
