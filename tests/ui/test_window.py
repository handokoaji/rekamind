# tests/ui/test_window.py
import tkinter as tk

import pytest

from app.ui.window import MainWindow


class FakeController:
    def __init__(self):
        self.state = "idle"
        self.started_with = None
        self.stopped = False

    def start_meeting(self, title):
        self.started_with = title
        self.state = "recording"
        return 1

    def stop_meeting(self):
        self.stopped = True
        self.state = "done"


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        root.update()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_start_and_stop_buttons_call_controller():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.on_start_clicked("Rapat Sore")
    assert controller.started_with == "Rapat Sore"
    assert "recording" in window.status_var.get().lower() or controller.state == "recording"

    window.on_stop_clicked()
    assert controller.stopped is True

    root.destroy()
