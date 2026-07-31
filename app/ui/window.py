# app/ui/window.py
import os
import sys
import tkinter as tk
from tkinter import scrolledtext, ttk
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
        self._title_entry = tk.Entry(root, textvariable=self.title_var, width=40)
        self._title_entry.pack(fill="x")

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", pady=4)
        self._start_button = tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start)
        self._start_button.pack(side="left")
        self._stop_button = tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop)
        self._stop_button.pack(side="left")

        self.status_label = tk.Label(root, textvariable=self.status_var)
        self.status_label.pack(anchor="w")

        self.progress_step_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.progress_step_var, fg="gray").pack(anchor="w")
        self._progress_bar = ttk.Progressbar(root, mode="indeterminate")
        self._progress_running = False

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
        # Guard: only allow start if currently idle/done/error (mirrors on_stop_clicked's
        # guard below). Start is only clickable in these states per refresh_status(), but
        # this closes the race for direct/rapid calls same as the stop-button fix.
        if self._controller.state not in ("idle", "done", "error"):
            return

        # Disable start button synchronously BEFORE spawning background thread so a
        # double-click can't fire start_meeting() twice while the heavy setup
        # (Diarizer/VAD construction) runs off the UI thread.
        self._start_button.config(state="disabled")

        def _start_in_background():
            try:
                self._controller.start_meeting(title)
            except Exception as exc:
                print(f"Error starting meeting: {exc}", file=sys.stderr)
            finally:
                self._root.after(0, self.refresh_status)

        threading.Thread(target=_start_in_background, daemon=True).start()

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
        # Title is locked once a meeting is in flight so it can't drift from
        # what was already saved to the DB / used for the docx filename.
        self._title_entry.config(state="normal" if is_idle else "disabled")
        self._update_progress_display()

    def _update_progress_display(self) -> None:
        state = self._controller.state
        active = state in ("recording", "processing")
        if active and not self._progress_running:
            self._progress_bar.pack(fill="x", pady=2)
            self._progress_bar.start(50)
            self._progress_running = True
        elif not active and self._progress_running:
            self._progress_bar.stop()
            self._progress_bar.pack_forget()
            self._progress_running = False

        if state == "processing":
            self.progress_step_var.set(getattr(self._controller, "processing_step", "") or "Memproses...")
        elif state == "recording":
            self.progress_step_var.set("Merekam...")
        else:
            self.progress_step_var.set("")

    def push_live_event(self, event: dict) -> None:
        """Thread-safe: called from LiveSession's background threads."""
        self._live_events.put(event)

    def _is_scrolled_to_bottom(self) -> bool:
        _, bottom_fraction = self.transcript_view.yview()
        return bottom_fraction >= 0.999

    def _drain_live_events(self) -> None:
        try:
            while True:
                event = self._live_events.get_nowait()
                if event["type"] == "text":
                    segment = event["segment"]
                    if segment is not None:
                        follow = self._is_scrolled_to_bottom()
                        self.transcript_view.insert("end", f"{segment.text}\n")
                        if follow:
                            self.transcript_view.see("end")
                elif event["type"] == "relabel":
                    # A full clear+reinsert always resets the view to the top;
                    # follow the bottom if the user was there, otherwise keep
                    # them roughly where they were instead of yanking them up.
                    follow = self._is_scrolled_to_bottom()
                    scroll_fraction = self.transcript_view.yview()[0]
                    self.transcript_view.delete("1.0", "end")
                    for seg in event["segments"]:
                        self.transcript_view.insert("end", f"{seg.speaker_label}: {seg.text}\n")
                    if follow:
                        self.transcript_view.see("end")
                    else:
                        self.transcript_view.yview_moveto(scroll_fraction)
        except queue.Empty:
            pass
        finally:
            self._update_progress_display()
            self._root.after(200, self._drain_live_events)
