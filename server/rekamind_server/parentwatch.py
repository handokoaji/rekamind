"""Exit when the process that started us is gone.

The desktop app starts the backend as a child. If the app is killed hard (crash, Task Manager, power
loss) the child would otherwise live on, holding the port and a full copy of the models, and the next
launch would find an unauthenticated stranger on its port. Polling the parent is portable, needs no OS
job objects, and is cheap (one syscall every few seconds).
"""
from __future__ import annotations

import os
import sys
import threading
import time


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    return True


def watch(parent_pid: int, interval: float = 3.0, on_gone=lambda: os._exit(0)) -> threading.Thread:  # noqa: B008
    def loop() -> None:
        while pid_alive(parent_pid):
            time.sleep(interval)
        on_gone()

    t = threading.Thread(target=loop, name="parent-watch", daemon=True)
    t.start()
    return t


def watch_from_env(interval: float = 3.0) -> bool:
    raw = os.environ.get("REKAMIND_PARENT_PID", "")
    if not raw.isdigit():
        return False
    watch(int(raw), interval)
    return True
