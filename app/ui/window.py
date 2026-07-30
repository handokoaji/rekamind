# app/ui/window.py
import sys
import tkinter as tk
from tkinter import scrolledtext
import threading

from app.ui.controller import RecorderController

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "processing": "Memproses transkrip & MoM...",
    "done": "Selesai",
    "error": "Gagal, lihat log",
}


class MainWindow:
    def __init__(self, root: tk.Tk, controller: RecorderController):
        self._root = root
        self._controller = controller
        self._root.title("Meeting Recorder")

        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value=_STATUS_LABELS["idle"])

        tk.Label(root, text="Judul Meeting:").pack(anchor="w")
        tk.Entry(root, textvariable=self.title_var, width=40).pack(fill="x")

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", pady=4)
        self._start_button = tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start)
        self._start_button.pack(side="left")
        self._stop_button = tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop)
        self._stop_button.pack(side="left")

        tk.Label(root, textvariable=self.status_var).pack(anchor="w")
        self.transcript_view = scrolledtext.ScrolledText(root, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def on_start_clicked(self, title: str) -> None:
        try:
            self._controller.start_meeting(title)
        except Exception as exc:
            print(f"Error starting meeting: {exc}", file=sys.stderr)
        finally:
            self.refresh_status()

    def on_stop_clicked(self) -> None:
        # Guard: only allow stop if currently recording
        if self._controller.state != "recording":
            return

        # Disable stop button synchronously BEFORE spawning background thread
        # to prevent double-click during processing window
        self._stop_button.config(state="disabled")

        def _stop_in_background():
            try:
                self._controller.stop_meeting()
            except Exception as exc:
                print(f"Error stopping meeting: {exc}", file=sys.stderr)
            finally:
                self._root.after(0, self.refresh_status)

        threading.Thread(target=_stop_in_background, daemon=True).start()

    def refresh_status(self) -> None:
        self.status_var.set(_STATUS_LABELS.get(self._controller.state, self._controller.state))
        # Enable/disable buttons based on state
        is_idle = self._controller.state in ("idle", "done", "error")
        self._start_button.config(state="normal" if is_idle else "disabled")
        self._stop_button.config(state="normal" if self._controller.state == "recording" else "disabled")
