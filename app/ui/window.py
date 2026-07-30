# app/ui/window.py
import os
import sys
import tkinter as tk
from tkinter import scrolledtext
import threading
import queue

from app.ui.controller import RecorderController

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "processing": "Memproses transkrip & MoM...",
    "done": "Selesai",
    "error": "Gagal, lihat log",
}

_STATUS_COLORS = {
    "idle": "black",
    "recording": "red",
    "processing": "#b8860b",  # dark goldenrod, readable on light/dark backgrounds
    "done": "green",
    "error": "red",
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

        self.status_label = tk.Label(root, textvariable=self.status_var)
        self.status_label.pack(anchor="w")

        self._open_docx_button = tk.Button(
            root, text="Buka Hasil (docx)", command=self._handle_open_docx, state="disabled"
        )
        self._open_docx_button.pack(anchor="w", pady=2)

        self.transcript_view = scrolledtext.ScrolledText(root, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

        self._live_events: "queue.Queue" = queue.Queue()
        self._root.after(200, self._drain_live_events)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def _handle_open_docx(self) -> None:
        docx_path = self._controller.last_docx_path
        if docx_path:
            os.startfile(docx_path)

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
        state = self._controller.state
        status = _STATUS_LABELS.get(state, state)
        if state == "error" and self._controller.error_message:
            status = f"{status}: {self._controller.error_message}"
        self.status_var.set(status)
        self.status_label.config(fg=_STATUS_COLORS.get(state, "black"))
        # Enable/disable buttons based on state
        is_idle = state in ("idle", "done", "error")
        self._start_button.config(state="normal" if is_idle else "disabled")
        self._stop_button.config(state="normal" if state == "recording" else "disabled")
        can_open_docx = state == "done" and bool(self._controller.last_docx_path)
        self._open_docx_button.config(state="normal" if can_open_docx else "disabled")

    def push_live_event(self, event: dict) -> None:
        """Thread-safe: called from LiveSession's background threads."""
        self._live_events.put(event)

    def _drain_live_events(self) -> None:
        try:
            while True:
                event = self._live_events.get_nowait()
                if event["type"] == "text":
                    segment = event["segment"]
                    if segment is not None:
                        self.transcript_view.insert("end", f"{segment.text}\n")
                elif event["type"] == "relabel":
                    self.transcript_view.delete("1.0", "end")
                    for seg in event["segments"]:
                        self.transcript_view.insert("end", f"{seg.speaker_label}: {seg.text}\n")
        except queue.Empty:
            pass
        finally:
            self._root.after(200, self._drain_live_events)
