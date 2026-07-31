import logging
import os
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

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


class HistoryView(tk.Frame):
    def __init__(self, parent: tk.Widget, controller):
        super().__init__(parent)
        self._controller = controller
        self._meetings_by_iid: dict[str, object] = {}

        self._tree = ttk.Treeview(self, columns=("title", "date", "status"), show="headings", height=10)
        self._tree.heading("title", text="Judul")
        self._tree.heading("date", text="Tanggal")
        self._tree.heading("status", text="Status")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        action_frame = tk.Frame(self)
        action_frame.pack(fill="x", pady=4)
        self._status_label = tk.Label(action_frame, text="")
        self._status_label.pack(anchor="w")

        self._transcribe_button = tk.Button(action_frame, text="Transkrip", command=self._handle_transcribe)
        self._summarize_button = tk.Button(action_frame, text="Ringkasan", command=self._handle_summarize)
        self._retry_button = tk.Button(action_frame, text="Coba Lagi", command=self._handle_retry)
        self._download_button = tk.Button(action_frame, text="Unduh Docx", command=self._handle_download)
        self._view_transcript_button = tk.Button(action_frame, text="Lihat Transkrip", command=self._handle_view_transcript)

        self._transcript_view = scrolledtext.ScrolledText(self, height=10, width=60)

        self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        self.refresh()
        self.after(_REFRESH_INTERVAL_MS, self._poll)

    def refresh(self) -> None:
        meetings = self._controller.list_meetings()
        previously_selected = self._tree.selection()
        self._tree.delete(*self._tree.get_children())
        self._meetings_by_iid.clear()
        for meeting in meetings:
            date_str = meeting.start_time.strftime("%Y-%m-%d %H:%M") if meeting.start_time else "-"
            iid = str(meeting.id)
            self._tree.insert("", "end", iid=iid, values=(
                meeting.title, date_str, _STATUS_LABELS.get(meeting.status, meeting.status),
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
        for button in (
            self._transcribe_button, self._summarize_button, self._retry_button,
            self._download_button, self._view_transcript_button,
        ):
            button.pack_forget()
        self._transcript_view.pack_forget()

        meeting = self._selected_meeting()
        if meeting is None:
            self._status_label.config(text="")
            return

        status = meeting.status
        label = _STATUS_LABELS.get(status, status)
        if status == "failed" and meeting.error_message:
            label = f"{label} -- {meeting.error_message}"
        self._status_label.config(text=label)

        if status == "recorded":
            self._transcribe_button.pack(side="left")
        elif status == "transcribed":
            self._summarize_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "completed":
            self._download_button.pack(side="left")
            self._view_transcript_button.pack(side="left")
        elif status == "failed":
            self._retry_button.pack(side="left")

    def _run_in_background(self, fn, meeting_id: int) -> None:
        def _worker():
            try:
                fn(meeting_id)
            except Exception as exc:
                logger.warning("history action failed for meeting %s: %s", meeting_id, exc)
            finally:
                self.after(0, self.refresh)

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_transcribe(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.run_transcribe, meeting.id)

    def _handle_summarize(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.run_summarize, meeting.id)

    def _handle_retry(self) -> None:
        meeting = self._selected_meeting()
        if meeting is not None:
            self._run_in_background(self._controller.retry, meeting.id)

    def _handle_download(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        docx_path = self._controller.get_docx_path(meeting.id)
        if docx_path:
            os.startfile(docx_path)

    def _handle_view_transcript(self) -> None:
        meeting = self._selected_meeting()
        if meeting is None:
            return
        rows = self._controller.get_transcript(meeting.id)
        self._transcript_view.pack(fill="both", expand=True)
        self._transcript_view.delete("1.0", "end")
        for label, text in rows:
            self._transcript_view.insert("end", f"{label}: {text}\n")
