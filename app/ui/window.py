# app/ui/window.py
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext
import threading
import queue
import webbrowser

from app import update_check
from app.config import get_settings
from app.settings_store import save_packaged_config
from app.ui.controller import RecorderController
from app.ui.history_view import HistoryView
from app.ui.setup_wizard import SetupWizard

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "error": "Gagal, lihat log",
}

_STATUS_COLORS = {
    "idle": "black",
    "recording": "red",
    "error": "red",
}


class MainWindow:
    def __init__(self, root: tk.Tk, controller: RecorderController):
        self._root = root
        self._controller = controller
        self._root.title("Rekamind")

        nav = tk.Frame(root)
        nav.pack(fill="x")
        tk.Button(nav, text="Meeting Baru", command=self._show_recording).pack(side="left")
        tk.Button(nav, text="Riwayat", command=self._show_history).pack(side="left")
        tk.Button(nav, text="Pengaturan", command=self._handle_open_settings).pack(side="left")

        container = tk.Frame(root)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._recording_frame = tk.Frame(container)
        self._recording_frame.grid(row=0, column=0, sticky="nsew")
        self._build_recording_frame(self._recording_frame)

        self._history_view = HistoryView(container, controller)
        self._history_view.grid(row=0, column=0, sticky="nsew")

        self._show_recording()

    def _show_recording(self) -> None:
        self._recording_frame.tkraise()
        # Stops the 2s DB poll while Riwayat is hidden behind this frame.
        self._history_view.set_active(False)

    def _show_history(self) -> None:
        self._history_view.tkraise()
        self._history_view.set_active(True)

    def _handle_open_settings(self) -> None:
        settings = get_settings()
        initial = {
            "storage_backend": settings.storage_backend,
            "postgres_host": settings.postgres_host,
            "postgres_port": settings.postgres_port,
            "postgres_user": settings.postgres_user,
            "postgres_password": settings.postgres_password,
            "postgres_db": settings.postgres_db,
            "groq_api_key": settings.groq_api_key,
            "hf_token": settings.hf_token,
        }
        result = SetupWizard(parent=self._root, initial=initial).run()
        if result is not None:
            save_packaged_config(result)
            messagebox.showinfo("Pengaturan", "Restart aplikasi untuk menerapkan perubahan.")

    def _build_recording_frame(self, parent: tk.Widget) -> None:
        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value=_STATUS_LABELS["idle"])

        tk.Label(parent, text="Judul Meeting:").pack(anchor="w")
        self._title_entry = tk.Entry(parent, textvariable=self.title_var, width=40)
        self._title_entry.pack(fill="x")

        button_frame = tk.Frame(parent)
        button_frame.pack(fill="x", pady=4)
        self._start_button = tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start)
        self._start_button.pack(side="left")
        self._stop_button = tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop)
        self._stop_button.pack(side="left")

        self.status_label = tk.Label(parent, textvariable=self.status_var)
        self.status_label.pack(anchor="w")

        self.live_warning_var = tk.StringVar()
        self.live_warning_label = tk.Label(parent, textvariable=self.live_warning_var, fg="orange")
        self.live_warning_label.pack(anchor="w")

        # Toggled only by real "heartbeat" events (WAV size actually grew) --
        # not a timer -- so it freezes the instant capture dies instead of
        # animating forever over a session that silently stopped recording.
        self._pulse_on = False
        self.recording_pulse_var = tk.StringVar()
        self.recording_pulse_label = tk.Label(parent, textvariable=self.recording_pulse_var, fg="green")
        self.recording_pulse_label.pack(anchor="w")

        self.update_notice_var = tk.StringVar()
        self.update_notice_label = tk.Label(parent, textvariable=self.update_notice_var, fg="blue", cursor="hand2")
        self.update_notice_label.pack(anchor="w")
        self.update_notice_label.bind("<Button-1>", self._handle_update_notice_click)

        self.transcript_view = scrolledtext.ScrolledText(parent, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

        self._live_events: "queue.Queue" = queue.Queue()
        self._root.after(200, self._drain_live_events)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def on_start_clicked(self, title: str) -> None:
        # Guard: only allow start if currently idle/error (mirrors on_stop_clicked's
        # guard below). Start is only clickable in these states per refresh_status(), but
        # this closes the race for direct/rapid calls same as the stop-button fix.
        if self._controller.state not in ("idle", "error"):
            return

        # Disable start button synchronously BEFORE spawning background thread so a
        # double-click can't fire start_meeting() twice while the heavy setup
        # (Diarizer/VAD construction) runs off the UI thread.
        self._start_button.config(state="disabled")
        self.live_warning_var.set("")  # clear any stale warning from the previous meeting
        self.recording_pulse_var.set("menunggu data rekaman...")

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
                self._root.after(0, self._history_view.refresh)

        threading.Thread(target=_stop_in_background, daemon=True).start()

    def refresh_status(self) -> None:
        state = self._controller.state
        status = _STATUS_LABELS.get(state, state)
        if state == "error" and self._controller.error_message:
            status = f"{status}: {self._controller.error_message}"
        self.status_var.set(status)
        self.status_label.config(fg=_STATUS_COLORS.get(state, "black"))
        # Enable/disable buttons based on state
        is_idle = state in ("idle", "error")
        self._start_button.config(state="normal" if is_idle else "disabled")
        self._stop_button.config(state="normal" if state == "recording" else "disabled")
        if state != "recording":
            self.recording_pulse_var.set("")
        # Title is locked once a meeting is in flight so it can't drift from
        # what was already saved to the DB.
        self._title_entry.config(state="normal" if is_idle else "disabled")

    def _handle_update_notice_click(self, event=None) -> None:
        if update_check.RELEASES_PAGE_URL:
            webbrowser.open(update_check.RELEASES_PAGE_URL)

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
                elif event["type"] == "warning":
                    self.live_warning_var.set(event["message"])
                elif event["type"] == "heartbeat":
                    self._pulse_on = not self._pulse_on
                    symbol = "●" if self._pulse_on else "○"  # ● / ○
                    self.recording_pulse_var.set(f"{symbol} merekam (data masuk)")
                elif event["type"] == "update_available":
                    self.update_notice_var.set(f"Update tersedia: v{event['version']} -- klik untuk buka halaman unduh")
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
            self._root.after(200, self._drain_live_events)
