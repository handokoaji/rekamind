import threading
import tkinter as tk
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ui.history_view import HistoryView


def _pump_until(root: tk.Tk, predicate, timeout: float = 5.0) -> None:
    """Background threads hand work back via self.after(...), which Tkinter only
    honors while the main thread is inside mainloop() -- same helper/reasoning as
    tests/ui/test_window.py."""
    deadline = time.time() + timeout

    def _check():
        if predicate() or time.time() > deadline:
            root.quit()
            return
        root.after(20, _check)

    root.after(20, _check)
    root.mainloop()


def _transcript_shown(view: HistoryView) -> bool:
    """ScrolledText proxies pack()/pack_forget() to an inner frame, so
    winfo_manager() on the widget itself is always "pack" -- only the frame
    reflects whether the panel is actually on screen."""
    return str(view._transcript_view.frame.winfo_manager()) == "pack"


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        root.update()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


def _meeting(id, title, status, error_message=None, failed_stage=None, device_label=None, end_time=None):
    return SimpleNamespace(
        id=id, title=title, status=status,
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        error_message=error_message, failed_stage=failed_stage, device_label=device_label,
        end_time=end_time,
    )


class FakeController:
    def __init__(self, meetings):
        self._meetings = meetings
        self.transcribe_calls = []
        self.summarize_calls = []
        self.retry_calls = []
        self.download_calls = []
        self.delete_calls = []
        self.transcript_by_id = {}
        self.list_meetings_calls = 0
        self.minio_configured = False
        self.sync_calls = 0
        self.sync_result = {"manifests": 0, "uploaded": 0, "pulled": 0}

    def sync_now(self):
        self.sync_calls += 1
        return self.sync_result

    def list_meetings(self):
        self.list_meetings_calls += 1
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

    def delete_meeting(self, meeting_id):
        self.delete_calls.append(meeting_id)
        self._meetings = [m for m in self._meetings if m.id != meeting_id]


class GatedController(FakeController):
    """run_transcribe blocks until the test releases it, so "an action is in
    flight" is a state the test can actually observe."""

    def __init__(self, meetings):
        super().__init__(meetings)
        self.gate = threading.Event()

    def run_transcribe(self, meeting_id):
        self.gate.wait(5)
        self.transcribe_calls.append(meeting_id)


class ExplodingController(FakeController):
    def run_transcribe(self, meeting_id):
        raise ValueError(
            "Meeting ini tidak punya lokasi rekaman yang tersimpan, tidak bisa ditranskrip"
        )


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

    # Wait for background thread to complete (polling with timeout)
    timeout = 2.0
    start = time.time()
    while len(controller.transcribe_calls) == 0 and time.time() - start < timeout:
        time.sleep(0.01)

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
def test_transcript_stays_visible_across_a_poll_refresh():
    """Finding 1: the 2s poll used to pack_forget() the transcript panel on every
    refresh, so "Lihat Transkrip" vanished within 2 seconds of being opened."""
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "transcribed")])
    controller.transcript_by_id[1] = [("Anda", "Selamat pagi")]
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()
    view._handle_view_transcript()
    assert _transcript_shown(view)

    view.refresh()  # what _poll() does every 2 seconds

    assert _transcript_shown(view)
    assert "Anda: Selamat pagi" in view._transcript_view.get("1.0", "end")
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_transcript_hidden_when_selection_moves_to_another_meeting():
    root = tk.Tk()
    controller = FakeController([
        _meeting(1, "Rapat A", "transcribed"),
        _meeting(2, "Rapat B", "transcribed"),
    ])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()
    view._handle_view_transcript()
    assert _transcript_shown(view)

    view._tree.selection_set("2")
    view._on_select()

    assert not _transcript_shown(view)
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_poll_skips_the_db_query_while_the_tab_is_inactive():
    """Finding 2: every tick is a fresh asyncpg connection + query on the Tk main
    thread, so it must only run while the Riwayat tab is the one on top."""
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)
    after_construction = controller.list_meetings_calls

    view._poll()
    assert controller.list_meetings_calls == after_construction, "inactive tab must not hit the DB"

    view.set_active(True)
    assert controller.list_meetings_calls == after_construction + 1, "becoming active refreshes at once"

    view._poll()
    assert controller.list_meetings_calls == after_construction + 2

    view.set_active(False)
    view._poll()
    assert controller.list_meetings_calls == after_construction + 2
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_action_button_disabled_on_click_and_stays_disabled_across_refresh():
    """Finding 7: a double-click before the status changes would run the stage
    twice (which is what makes findings 4 and 5 reachable)."""
    root = tk.Tk()
    controller = GatedController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()
    assert view._transcribe_button.cget("state") == "normal"

    view._handle_transcribe()
    assert view._transcribe_button.cget("state") == "disabled", "must disable synchronously"

    # A poll-driven refresh lands before the DB status has changed to "transcribing".
    view.refresh()
    assert view._transcribe_button.cget("state") == "disabled", "refresh must not re-enable an in-flight action"

    view._handle_transcribe()  # the double-click

    # Release the worker from inside the event loop: it calls self.after(...) when
    # it finishes, which Tkinter only accepts while the main thread is in
    # mainloop(). Waiting on the refresh it schedules (rather than on the call
    # list the worker itself appends to) guarantees those after() calls are done
    # before the loop is torn down.
    refreshes_before = controller.list_meetings_calls
    root.after(10, controller.gate.set)
    _pump_until(root, lambda: controller.list_meetings_calls > refreshes_before)

    assert controller.transcribe_calls == [1], "second click must not start a second run"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_failed_background_action_shows_its_message_in_the_status_label():
    """Finding 6b: the error was only logged, so the button looked like a no-op."""
    root = tk.Tk()
    controller = ExplodingController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    refreshes_before = controller.list_meetings_calls
    root.after(10, view._handle_transcribe)  # click from inside the running event loop
    _pump_until(root, lambda: controller.list_meetings_calls > refreshes_before)

    assert "tidak punya lokasi rekaman" in view._status_label.cget("text")
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_meeting_dates_are_rendered_in_wib_not_utc():
    """Finding 8: 09:00 UTC is a 16:00 WIB meeting."""
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded")])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")
    assert values[1] == "2026-07-31 16:00"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_delete_button_hidden_while_meeting_is_recording():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recording")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    assert str(view._delete_button.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_delete_button_shown_for_non_recording_status():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    assert str(view._delete_button.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_delete_asks_for_confirmation_and_deletes_on_yes(monkeypatch):
    root = tk.Tk()
    monkeypatch.setattr("app.ui.history_view.messagebox.askyesno", lambda *a, **k: True)
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_delete()

    timeout = 2.0
    start = time.time()
    while len(controller.delete_calls) == 0 and time.time() - start < timeout:
        time.sleep(0.01)

    assert controller.delete_calls == [1]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_delete_does_nothing_when_confirmation_declined(monkeypatch):
    root = tk.Tk()
    monkeypatch.setattr("app.ui.history_view.messagebox.askyesno", lambda *a, **k: False)
    controller = FakeController([_meeting(1, "Rapat A", "completed")])
    view = HistoryView(root, controller)
    view._tree.selection_set("1")
    view._on_select()

    view._handle_delete()
    time.sleep(0.1)

    assert controller.delete_calls == []
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


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_duration_column():
    root = tk.Tk()
    # start_time is fixed at 09:00 by the _meeting() helper.
    meeting = _meeting(1, "Rapat A", "completed", end_time=datetime(2026, 7, 31, 10, 41, tzinfo=timezone.utc))
    controller = FakeController([meeting])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[4] == "1j 41m"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_dash_duration_when_meeting_not_finished():
    root = tk.Tk()
    meeting = _meeting(1, "Rapat A", "recording")  # end_time defaults to None
    controller = FakeController([meeting])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[4] == "-"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_device_label_column():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded", device_label="Laptop Budi")])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[3] == "Laptop Budi"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_riwayat_shows_fallback_for_unknown_device():
    root = tk.Tk()
    controller = FakeController([_meeting(1, "Rapat A", "recorded", device_label=None)])
    view = HistoryView(root, controller)

    values = view._tree.item("1", "values")

    assert values[3] == "Tidak diketahui"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_sync_button_hidden_when_minio_not_configured():
    root = tk.Tk()
    controller = FakeController([])
    controller.minio_configured = False
    view = HistoryView(root, controller)

    assert str(view._sync_button.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_sync_button_shown_and_calls_controller_when_configured():
    root = tk.Tk()
    controller = FakeController([])
    controller.minio_configured = True
    controller.sync_result = {"manifests": 2, "uploaded": 1, "pulled": 3}
    view = HistoryView(root, controller)
    assert str(view._sync_button.winfo_manager()) == "pack"

    refreshes_before = controller.list_meetings_calls
    root.after(10, view._handle_sync)
    _pump_until(root, lambda: controller.list_meetings_calls > refreshes_before)

    assert controller.sync_calls == 1
    assert "3" in view._sync_status_label.cget("text")  # pulled count surfaced
    root.destroy()
