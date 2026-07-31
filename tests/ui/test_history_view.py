import tkinter as tk
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ui.history_view import HistoryView


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        root.update()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


def _meeting(id, title, status, error_message=None, failed_stage=None):
    return SimpleNamespace(
        id=id, title=title, status=status,
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        error_message=error_message, failed_stage=failed_stage,
    )


class FakeController:
    def __init__(self, meetings):
        self._meetings = meetings
        self.transcribe_calls = []
        self.summarize_calls = []
        self.retry_calls = []
        self.download_calls = []
        self.transcript_by_id = {}

    def list_meetings(self):
        return self._meetings

    def run_transcribe(self, meeting_id):
        self.transcribe_calls.append(meeting_id)

    def run_summarize(self, meeting_id):
        self.summarize_calls.append(meeting_id)

    def retry(self, meeting_id):
        self.retry_calls.append(meeting_id)

    def get_transcript(self, meeting_id):
        return self.transcript_by_id.get(meeting_id, [])

    def get_docx_path(self, meeting_id):
        self.download_calls.append(meeting_id)
        return "C:/recordings/1/mom.docx"


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_refresh_populates_treeview_rows():
    root = tk.Tk()
    controller = FakeController([
        _meeting(1, "Rapat A", "recorded"),
        _meeting(2, "Rapat B", "completed"),
    ])
    view = HistoryView(root, controller)

    children = view._tree.get_children()
    assert len(children) == 2
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_recorded_meeting_shows_transcribe_button():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._transcribe_button.winfo_manager()) == "pack"
    assert str(view._summarize_button.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_transcribed_meeting_shows_summarize_and_view_transcript_buttons():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "transcribed")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._summarize_button.winfo_manager()) == "pack"
    assert str(view._view_transcript_button.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_failed_meeting_shows_retry_button_and_error_message():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "failed", error_message="Groq timeout")])
    view = HistoryView(root, controller)

    view._tree.selection_set("1")
    view._on_select()

    assert str(view._retry_button.winfo_manager()) == "pack"
    assert "Groq timeout" in view._status_label.cget("text")
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_transcribe_button_calls_controller_run_transcribe():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_transcribe()

    assert controller.transcribe_calls == [1]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_view_transcript_renders_lines_in_transcript_view():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "transcribed")])
    controller.transcript_by_id[1] = [("Anda", "Selamat pagi"), ("Speaker 1", "Mari mulai")]
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_view_transcript()

    content = view._transcript_view.get("1.0", "end")
    assert "Anda: Selamat pagi" in content
    assert "Speaker 1: Mari mulai" in content
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_download_button_calls_controller_get_docx_path(monkeypatch):
    root = tk.Tk()
    opened = []
    monkeypatch.setattr("app.ui.history_view.os.startfile", lambda path: opened.append(path))
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_download()

    assert opened == ["C:/recordings/1/mom.docx"]
    root.destroy()
