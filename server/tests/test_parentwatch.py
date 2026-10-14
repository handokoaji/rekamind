import subprocess
import sys
import time

from rekamind_server import parentwatch


def test_pid_alive_knows_itself_and_a_finished_process():
    import os

    assert parentwatch.pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not parentwatch.pid_alive(p.pid)
    assert not parentwatch.pid_alive(0) and not parentwatch.pid_alive(-5)


def test_the_backend_exits_by_itself_when_its_parent_dies():
    # parent (this test) -> middle (dies right away) -> child (watches the middle and must exit)
    child_code = (
        "import sys,time,os;from rekamind_server import parentwatch;"
        "parentwatch.watch(int(sys.argv[1]),0.1);print(os.getpid(),flush=True);time.sleep(30)"
    )
    middle_code = (
        "import subprocess,sys,os;"
        f"c=subprocess.Popen([sys.executable,'-c',{child_code!r},str(os.getpid())],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True);"
        "print(c.stdout.readline().strip(),flush=True)"
    )
    middle = subprocess.run([sys.executable, "-c", middle_code], capture_output=True, text=True, timeout=20)  # noqa: S603
    child_pid = int(middle.stdout.strip())
    deadline = time.time() + 10
    while parentwatch.pid_alive(child_pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not parentwatch.pid_alive(child_pid), "orphaned backend kept running"


def test_without_a_parent_variable_nothing_is_watched(monkeypatch):
    monkeypatch.delenv("REKAMIND_PARENT_PID", raising=False)
    assert parentwatch.watch_from_env() is False
    monkeypatch.setenv("REKAMIND_PARENT_PID", "not-a-number")
    assert parentwatch.watch_from_env() is False
