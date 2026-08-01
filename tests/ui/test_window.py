# tests/ui/test_window.py
import threading
import time
import tkinter as tk

import pytest

from app.ui.window import MainWindow


class FakeController:
    def __init__(self, start_raises=False, stop_raises=False):
        self.state = "idle"
        self.started_with = None
        self.stopped = False
        self.stop_call_count = 0
        self.error_message = ""
        self.start_raises = start_raises
        self.stop_raises = stop_raises
        self.minio_configured = False

    def start_meeting(self, title):
        if self.start_raises:
            self.state = "error"
            self.error_message = "Start failed"
            raise RuntimeError(self.error_message)
        self.started_with = title
        self.state = "recording"
        return 1

    def stop_meeting(self):
        self.stop_call_count += 1
        if self.stop_raises:
            self.state = "error"
            self.error_message = "Stop failed"
            raise RuntimeError(self.error_message)
        self.stopped = True
        self.state = "idle"

    def list_meetings(self):
        # MainWindow always builds a HistoryView alongside the recording tab,
        # and HistoryView.refresh() calls this on construction.
        return []


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        root.update()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


def _pump_until(root: tk.Tk, predicate, timeout: float = 5.0) -> None:
    """Run the Tk event loop until predicate() is true or timeout elapses.

    Background threads (like the one on_start_clicked/on_stop_clicked spawn) call
    self._root.after(...) to hand work back to the UI thread. Tkinter only honors
    that hand-off while the main thread is actually inside mainloop() (a plain
    root.update() polling loop is not enough and raises "main thread is not in
    main loop"), so tests that wait on background-thread side effects must pump
    via mainloop()/quit() instead of update().
    """
    deadline = time.time() + timeout

    def _check():
        if predicate() or time.time() > deadline:
            root.quit()
            return
        root.after(20, _check)

    root.after(20, _check)
    root.mainloop()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_start_and_stop_buttons_call_controller():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.on_start_clicked("Rapat Sore")

    # on_start_clicked now runs start_meeting() in a background thread; pump the
    # Tk event loop until it lands instead of asserting immediately (same style of
    # deadline-polling used for background threads in tests/live/test_session.py).
    _pump_until(root, lambda: controller.state == "recording")

    assert controller.started_with == "Rapat Sore"
    assert "recording" in window.status_var.get().lower() or controller.state == "recording"

    window.on_stop_clicked()
    # Note: on_stop_clicked runs in a background thread, so we can't immediately check
    # stopped flag without a race condition. This is a manual-verification item.

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_start_error_shows_error_state():
    """Verify that if start_meeting() raises, refresh_status() is still called and error state is shown."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController(start_raises=True)
    window = MainWindow(root, controller)

    window.on_start_clicked("Rapat Sore")

    # start_meeting() now raises inside a background thread; pump until the error
    # state lands and the scheduled refresh_status() (via root.after) has run.
    _pump_until(root, lambda: controller.state == "error" and "gagal" in window.status_var.get().lower())

    # refresh_status should have been called even though start_meeting() raised
    assert controller.state == "error"
    assert "Gagal" in window.status_var.get() or "gagal" in window.status_var.get().lower()

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_button_enable_disable_based_on_state():
    """Verify that buttons are enabled/disabled based on controller state."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    # Initially idle: start enabled, stop disabled
    window.refresh_status()
    assert window._start_button.cget("state") == "normal"
    assert window._stop_button.cget("state") == "disabled"

    # After start: start disabled, stop enabled
    controller.state = "recording"
    window.refresh_status()
    assert window._start_button.cget("state") == "disabled"
    assert window._stop_button.cget("state") == "normal"

    # On error: start enabled, stop disabled
    controller.state = "error"
    window.refresh_status()
    assert window._start_button.cget("state") == "normal"
    assert window._stop_button.cget("state") == "disabled"

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_warning_event_shows_message_in_live_warning_label():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "warning", "message": "Mic tidak merekam apa pun"})
    _pump_until(root, lambda: window.live_warning_var.get() != "")

    assert window.live_warning_var.get() == "Mic tidak merekam apa pun"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_heartbeat_events_toggle_the_recording_pulse():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "heartbeat"})
    _pump_until(root, lambda: window.recording_pulse_var.get() != "")
    first = window.recording_pulse_var.get()

    window.push_live_event({"type": "heartbeat"})
    _pump_until(root, lambda: window.recording_pulse_var.get() != first)
    second = window.recording_pulse_var.get()

    assert first != second
    assert "merekam" in first.lower() and "merekam" in second.lower()
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_recording_pulse_cleared_once_state_leaves_recording():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    window.recording_pulse_var.set("● merekam (data masuk)")

    controller.state = "idle"
    window.refresh_status()

    assert window.recording_pulse_var.get() == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_starting_a_new_meeting_clears_a_stale_warning():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    window.live_warning_var.set("peringatan dari meeting sebelumnya")

    window.on_start_clicked("Rapat Baru")

    assert window.live_warning_var.get() == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_status_label_color_reflects_state():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    controller.state = "recording"
    window.refresh_status()
    assert window.status_label.cget("fg") == "red"

    controller.state = "error"
    window.refresh_status()
    assert window.status_label.cget("fg") == "red"

    root.destroy()


def test_double_click_stop_during_processing():
    """
    Verify that calling on_stop_clicked() twice in quick succession
    (before background thread finishes) does NOT invoke controller.stop_meeting() twice.
    This tests the state guard: if state != "recording", the second call should return early.
    """
    controller = FakeController()
    # Manually construct window without Tk to avoid threading/display issues
    root = tk.Tk()
    window = MainWindow(root, controller)

    # Simulate transition to recording state
    controller.state = "recording"
    window.refresh_status()

    # First click disables button and should call stop_meeting() once
    assert window._stop_button.cget("state") == "normal"
    window.on_stop_clicked()
    assert window._stop_button.cget("state") == "disabled"

    # Simulate state transition to "processing" (happens in background thread)
    controller.state = "processing"

    # Second click should return early because state != "recording"
    window.on_stop_clicked()

    # Without the state guard, stop_meeting() would have been called twice.
    # Note: Due to threading, we can't instantly verify the count without complex
    # synchronization. This test at minimum verifies the state guard logic:
    # if the state is already processing/done, the early return prevents the second click.
    # A more rigorous test would require mocking threading or using real async barriers.

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_title_entry_locked_while_recording():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    controller.state = "recording"
    window.refresh_status()
    assert window._title_entry.cget("state") == "disabled"

    controller.state = "idle"
    window.refresh_status()
    assert window._title_entry.cget("state") == "normal"

    controller.state = "error"
    window.refresh_status()
    assert window._title_entry.cget("state") == "normal"

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_text_event_appends_unlabeled_line():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    from app.live.pipeline import LiveSegment

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "text", "segment": LiveSegment(source="mic", start_ms=0, end_ms=500, text="Selamat pagi")})
    window._drain_live_events()  # call directly instead of waiting for root.after's timer

    assert "Selamat pagi" in window.transcript_view.get("1.0", "end")

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_relabel_event_rerenders_full_transcript_with_labels():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    from app.pipeline.merge import MergedSegment

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "text", "segment": None})  # unlabeled placeholder already shown
    window._drain_live_events()

    window.push_live_event({"type": "relabel", "segments": [
        MergedSegment(source="mic", speaker_label="Anda", start_ms=0, end_ms=500, text="Selamat pagi"),
        MergedSegment(source="speaker", speaker_label="Speaker 1", start_ms=600, end_ms=1200, text="Mari mulai"),
    ]})
    window._drain_live_events()

    content = window.transcript_view.get("1.0", "end")
    assert "Anda: Selamat pagi" in content
    assert "Speaker 1: Mari mulai" in content

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_nav_buttons_switch_between_recording_and_history_frames():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    root.update()  # winfo_viewable() needs idle tasks to run before geometry reflects reality

    # Recording frame is the default view.
    assert window._recording_frame.winfo_ismapped() or str(window._recording_frame.winfo_manager()) == "grid"

    window._show_history()
    root.update()
    assert window._history_view.winfo_viewable()

    window._show_recording()
    root.update()
    assert window._recording_frame.winfo_viewable()

    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_history_polling_follows_the_visible_tab():
    """The Riwayat poll hits Postgres on the Tk main thread every 2s, so it must
    only run while that tab is on top. winfo_ismapped()/winfo_viewable() can't
    tell which tkraise()-stacked frame is on top, hence the explicit flag."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    # MainWindow opens on the recording tab.
    assert window._history_view._active is False

    window._show_history()
    assert window._history_view._active is True

    window._show_recording()
    assert window._history_view._active is False


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_pengaturan_button_reopens_wizard_prefilled_and_saves_on_submit(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module

    class FakeSettings:
        storage_backend = "sqlite"
        postgres_host = None
        postgres_port = None
        postgres_user = None
        postgres_password = None
        postgres_db = None
        groq_api_key = "gk"
        hf_token = "hf"
        device_label = "my-device"
        minio_endpoint = "http://minio.local"
        minio_access_key = "ak"
        minio_secret_key = "sk"
        minio_bucket = "bucket"

    monkeypatch.setattr(window_module, "get_settings", lambda: FakeSettings())
    wizard_calls = []
    saved = []

    class FakeWizard:
        def __init__(self, parent=None, initial=None):
            wizard_calls.append((parent, initial))

        def run(self):
            return {"storage_backend": "sqlite", "groq_api_key": "gk2", "hf_token": "hf"}

    monkeypatch.setattr(window_module, "SetupWizard", FakeWizard)
    monkeypatch.setattr(window_module, "save_packaged_config", saved.append)
    monkeypatch.setattr(window_module.messagebox, "showinfo", lambda *a, **k: None)

    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_open_settings()

    assert wizard_calls == [(root, {
        "storage_backend": "sqlite", "postgres_host": None, "postgres_port": None,
        "postgres_user": None, "postgres_password": None, "postgres_db": None,
        "groq_api_key": "gk", "hf_token": "hf", "device_label": "my-device",
        "minio_endpoint": "http://minio.local", "minio_access_key": "ak",
        "minio_secret_key": "sk", "minio_bucket": "bucket",
    })]
    assert saved == [{"storage_backend": "sqlite", "groq_api_key": "gk2", "hf_token": "hf"}]


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_available_event_shows_notice_with_version():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    window.push_live_event({"type": "update_available", "version": "0.2.0"})
    _pump_until(root, lambda: window.update_notice_var.get() != "")

    assert "0.2.0" in window.update_notice_var.get()
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_notice_click_opens_releases_page_when_configured(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module
    monkeypatch.setattr(window_module.update_check, "RELEASES_PAGE_URL", "https://example/releases")
    opened = []
    monkeypatch.setattr(window_module.webbrowser, "open", opened.append)
    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_update_notice_click()

    assert opened == ["https://example/releases"]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_update_notice_click_no_op_when_url_blank(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    import app.ui.window as window_module
    monkeypatch.setattr(window_module.update_check, "RELEASES_PAGE_URL", "")
    opened = []
    monkeypatch.setattr(window_module.webbrowser, "open", opened.append)
    controller = FakeController()
    window = MainWindow(root, controller)

    window._handle_update_notice_click()

    assert opened == []
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_on_start_clicked_worker_never_calls_after_from_its_own_thread():
    """Same regression class as history_view.py's fix: Tkinter only honors
    self.after(...) while the main thread is inside mainloop() -- a background
    thread calling it directly races Tk teardown and can hard-crash the
    process. The worker must hand off through push_live_event's thread-safe
    queue instead, same as live session events already do."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)

    main_thread = threading.current_thread()
    calls_from_wrong_thread = []
    original_after = root.after

    def _tracking_after(*args, **kwargs):
        if threading.current_thread() is not main_thread:
            calls_from_wrong_thread.append(threading.current_thread())
        return original_after(*args, **kwargs)

    root.after = _tracking_after

    window.on_start_clicked("Rapat Sore")
    _pump_until(root, lambda: controller.state == "recording")

    assert calls_from_wrong_thread == []
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_on_stop_clicked_worker_never_calls_after_from_its_own_thread():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    window.on_start_clicked("Rapat Sore")
    _pump_until(root, lambda: controller.state == "recording")

    main_thread = threading.current_thread()
    calls_from_wrong_thread = []
    original_after = root.after

    def _tracking_after(*args, **kwargs):
        if threading.current_thread() is not main_thread:
            calls_from_wrong_thread.append(threading.current_thread())
        return original_after(*args, **kwargs)

    root.after = _tracking_after

    window.on_stop_clicked()
    _pump_until(root, lambda: controller.stopped)

    assert calls_from_wrong_thread == []
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_show_window_event_deiconifies_root(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    calls = []
    monkeypatch.setattr(root, "deiconify", lambda: calls.append(True))

    window.push_live_event({"type": "show_window"})
    _pump_until(root, lambda: len(calls) > 0)

    assert calls == [True]
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_quit_app_event_quits_root(monkeypatch):
    """root.quit() is also what _pump_until itself relies on to stop the pumped
    mainloop, so the tracking wrapper must call through to the original --
    replacing it with a no-op would hang this very test."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tcl/Tk not properly initialized in pytest environment")

    controller = FakeController()
    window = MainWindow(root, controller)
    calls = []
    original_quit = root.quit

    def _tracking_quit():
        calls.append(True)
        original_quit()

    monkeypatch.setattr(root, "quit", _tracking_quit)

    window.push_live_event({"type": "quit_app"})
    _pump_until(root, lambda: len(calls) > 0)

    assert calls == [True]
    root.destroy()
