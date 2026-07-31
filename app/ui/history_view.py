import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from app.timeutil import to_wib

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    "scheduled": "Terjadwal",
    "recording": "Merekam",
    "recorded": "Siap ditranskrip",
    "transcribing": "Sedang transkrip...",
    "transcribed": "Siap diringkas",
    "summarizing": "Sedang membuat ringkasan...",
    "completed": "Selesai",
    "failed": "Gagal",
}

_REFRESH_INTERVAL_MS = 2000


def _format_duration(meeting) -> str:
    if not meeting.start_time or not meeting.end_time:
        return "-"
    total_minutes = int((meeting.end_time - meeting.start_time).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}j {minutes}m"


class HistoryView(tk.Frame):
    def __init__(self, parent: tk.Widget, controller):
        super().__init__(parent)
        self._controller = controller
        self._meetings_by_iid: dict[str, object] = {}
        # Only poll while the Riwayat tab is the one on top: every tick is a
        # real round-trip to Postgres on the Tk main thread. tkraise()-stacked
        # frames both report winfo_ismapped()/winfo_viewable() true regardless
        # of which is on top, so MainWindow tells us explicitly instead.
        self._active = False
        # Which meeting "Lihat Transkrip" is currently showing, so a poll-driven
        # refresh of the SAME selection doesn't hide the transcript again.
        self._transcript_visible_for: int | None = None
        # Meetings with an action in flight: their button stays disabled across
        # refreshes until the status actually changes.
        self._busy_meeting_ids: set[int] = set()
        self._action_error: tuple[int, str] | None = None
        self._sync_in_progress = False
        # Background threads (transcribe/summarize/retry/delete/sync workers)
        # must never call self.after() themselves -- Tkinter only honors it
        # while the main thread is inside mainloop(), so a call from a worker
        # thread races Tk teardown and can hard-crash the process. They only
        # put callables here; only the main thread (via _drain_pending_actions,
        # itself scheduled through self.after) ever runs them.
        self._pending_actions: "queue.Queue" = queue.Queue()

        self._tree = ttk.Treeview(
            self, columns=("title", "date", "status", "device", "duration"), show="headings", height=10,
        )
        self._tree.heading("title", text="Judul")
        self._tree.heading("date", text="Tanggal")
        self._tree.heading("status", text="Status")
        self._tree.heading("device", text="Perangkat")
        self._tree.heading("duration", text="Durasi")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        action_frame = tk.Frame(self)
        action_frame.pack(fill="x", pady=4)
        self._status_label = tk.Label(action_frame, text="")
        self._status_label.pack(anchor="w")
        # Separate from _status_label: that one is reset to "" by
        # _update_action_panel() whenever no meeting is selected (a global
        # sync isn't tied to a selection), which would clobber a just-set
        # sync result the moment refresh() runs right after it.
        self._sync_status_label = tk.Label(action_frame, text="")
        self._sync_status_label.pack(anchor="w")

        self._transcribe_button = tk.Button(action_frame, text="Transkrip", command=self._handle_transcribe)
        self._summarize_button = tk.Button(action_frame, text="Ringkasan", command=self._handle_summarize)
        self._retry_button = tk.Button(action_frame, text="Coba Lagi", command=self._handle_retry)
        self._download_button = tk.Button(action_frame, text="Unduh Docx", command=self._handle_download)
        self._view_transcript_button = tk.Button(action_frame, text="Lihat Transkrip", command=self._handle_view_transcript)
        self._delete_button = tk.Button(action_frame, text="Hapus", command=self._handle_delete)
        self._sync_button = tk.Button(action_frame, text="Sync Sekarang", command=self._handle_sync)

        self._transcript_view = scrolledtext.ScrolledText(self, height=10, width=60)

        self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)
        self.after(100, self._drain_pending_actions)

    def set_active(self, is_active: bool) -> None:
        """Called by MainWindow when this tab is raised/left. Refreshing once on
        the way in keeps the list from being up to 2s stale when it appears."""
        self._active = is_active
        if is_active:
            self.refresh()

    def _poll(self) -> None:
        if self._active:
            self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)

    def refresh(self) -> None:
        meetings = self._controller.list_meetings()
        previously_selected = self._tree.selection()
        self._tree.delete(*self._tree.get_children())
        self._meetings_by_iid.clear()
        for meeting in meetings:
            # Stored UTC, displayed WIB.
            date_str = to_wib(meeting.start_time).strftime("%Y-%m-%d %H:%M") if meeting.start_time else "-"
            iid = str(meeting.id)
            self._tree.insert("", "end", iid=iid, values=(
                meeting.title, date_str, _STATUS_LABELS.get(meeting.status, meeting.status),
                meeting.device_label or "Tidak diketahui", _format_duration(meeting),
            ))
            self._meetings_by_iid[iid] = meeting
        if previously_selected and previously_selected[0] in self._meetings_by_iid:
            self._tree.selection_set(previously_selected[0])
        self._update_action_panel()

    def _selected_meeting(self):
        selection = self._tree.selection()
        if not selection:
            return None
        return self._meetings_by_iid.get(selection[0])

    def _on_select(self, event=None) -> None:
        self._update_action_panel()

    def _update_action_panel(self) -> None:
        if self._controller.minio_configured:
            self._sync_button.config(state="disabled" if self._sync_in_progress else "normal")
            self._sync_button.pack(side="right")
        else:
            self._sync_button.pack_forget()

        for button in (
            self._transcribe_button, self._summarize_button, self._retry_button,
            self._download_button, self._view_transcript_button, self._delete_button,
        ):
            button.pack_forget()

        meeting = self._selected_meeting()
        # The transcript panel is hidden only when the selection moved away from
        # the meeting it belongs to -- NOT on every refresh, or the 2s poll would
        # yank it off screen right after the user opened it.
        if meeting is None or meeting.id != self._transcript_visible_for:
            self._transcript_visible_for = None
            self._transcript_view.pack_forget()

        if meeting is None:
            self._status_label.config(text="")
            return

        status = meeting.status
        label = _STATUS_LABELS.get(status, status)
        if status == "failed" and meeting.error_message:
            label = f"{label} -- {meeting.error_message}"
        elif self._action_error is not None and self._action_error[0] == meeting.id:
            # Only when the pipeline itself didn't record one: an action can fail
            # before it ever reaches the DB (e.g. a meeting with no recording_dir),
            # which would otherwise leave the button looking like a no-op.
            label = f"{label} -- {self._action_error[1]}"
        self._status_label.config(text=label)

        state = "disabled" if meeting.id in self._busy_meeting_ids else "normal"
        is_own = meeting.device_id is None or meeting.device_id == self._controller.local_device_id
        if status == "recorded" and is_own:
            self._transcribe_button.config(state=state)
            self._transcribe_button.pack(side="left")
        elif status == "transcribed":
            if is_own:
                self._summarize_button.config(state=state)
                self._summarize_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "completed":
            self._download_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "failed" and is_own:
            self._retry_button.config(state=state)
            self._retry_button.pack(side="left")

        # Never while it's the one actively being recorded -- everything else
        # (including mid-pipeline states left over from a crash) is deletable.
        if status != "recording":
            self._delete_button.config(state=state)
            self._delete_button.pack(side="right")

    def _drain_pending_actions(self) -> None:
        try:
            while True:
                callback = self._pending_actions.get_nowait()
                callback()
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_pending_actions)

    def _run_in_background(self, fn, meeting_id: int) -> threading.Thread:
        def _worker():
            try:
                fn(meeting_id)
            except Exception as exc:
                logger.warning("history action failed for meeting %s: %s", meeting_id, exc)
                message = f"Gagal menjalankan aksi: {exc}"
                # Kept in a field, not just written to the label: the refresh
                # scheduled below rebuilds the panel and would wipe a bare label.
                self._action_error = (meeting_id, message)
                self._pending_actions.put(lambda: self._status_label.config(text=message))
            finally:
                self._busy_meeting_ids.discard(meeting_id)
                self._pending_actions.put(self.refresh)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return thread

    def _start_action(self, button: tk.Button, fn) -> None:
        """Disable the button synchronously BEFORE the thread starts (same
        pattern as window.py's on_start_clicked) so a double-click can't run the
        stage twice while the status in the DB hasn't caught up yet."""
        meeting = self._selected_meeting()
        if meeting is None or meeting.id in self._busy_meeting_ids:
            return
        if self._action_error is not None and self._action_error[0] == meeting.id:
            self._action_error = None
        self._busy_meeting_ids.add(meeting.id)
        button.config(state="disabled")
        self._run_in_background(fn, meeting.id)

    def _handle_transcribe(self) -> None:
        self._start_action(self._transcribe_button, self._controller.run_transcribe)

    def _handle_summarize(self) -> None:
        self._start_action(self._summarize_button, self._controller.run_summarize)

    def _handle_retry(self) -> None:
        self._start_action(self._retry_button, self._controller.retry)

    def _handle_download(self) -> None:
        # Deliberately synchronous, not routed through _start_action's
        # background-thread pattern. For a meeting recorded on this device
        # (the common case) ensure_docx_available returns immediately,
        # identical to the old get_docx_path -- only a meeting pulled from
        # another device and not yet cached locally pays a brief synchronous
        # MinIO download.
        meeting = self._selected_meeting()
        if meeting is None:
            return
        docx_path = self._controller.ensure_docx_available(meeting.id)
        if docx_path:
            os.startfile(docx_path)

    def _handle_delete(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None or meeting.id in self._busy_meeting_ids:
            return
        confirmed = messagebox.askyesno(
            "Hapus meeting",
            f"Yakin ingin menghapus \"{meeting.title}\"?\n\n"
            "Ini akan menghapus SEMUA data meeting ini secara permanen, "
            "termasuk transkrip, ringkasan, dan file rekaman audionya. "
            "Tindakan ini tidak bisa dibatalkan.",
            icon="warning",
        )
        if not confirmed:
            return
        self._start_action(self._delete_button, self._controller.delete_meeting)

    def _handle_sync(self) -> None:
        if self._sync_in_progress:
            return
        self._sync_in_progress = True
        self._sync_button.config(state="disabled")

        def _worker():
            try:
                result = self._controller.sync_now()
                message = (
                    f"Sync selesai: {result['manifests']} meeting diunggah, "
                    f"{result['uploaded']} file diunggah, {result['pulled']} meeting ditarik."
                )
            except Exception as exc:
                logger.warning("sync failed: %s", exc)
                message = f"Sync gagal: {exc}"
            finally:
                self._sync_in_progress = False
                self._pending_actions.put(lambda: self._sync_status_label.config(text=message))
                self._pending_actions.put(self.refresh)

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_view_transcript(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        rows = self._controller.get_transcript(meeting.id)
        self._transcript_visible_for = meeting.id
        self._transcript_view.pack(fill="both", expand=True)
        self._transcript_view.delete("1.0", "end")
        for label, text in rows:
            self._transcript_view.insert("end", f"{label}: {text}\n")
