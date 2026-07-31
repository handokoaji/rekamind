from concurrent.futures import BrokenExecutor, TimeoutError as FutureTimeoutError

from app.diarization.diarizer import SpeakerSegment
from app.live.diarize_worker import ProcessIsolatedDiarizer


class FakeFuture:
    def __init__(self, result=None, exception=None):
        self._result = result
        self._exception = exception

    def result(self, timeout=None):
        if self._exception is not None:
            raise self._exception
        return self._result


class FakeProcess:
    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


class FakeExecutor:
    instances = []

    def __init__(self, max_workers=None, initializer=None, initargs=None):
        self.max_workers = max_workers
        self.initializer = initializer
        self.initargs = initargs
        self.submitted = []
        self.shutdown_calls = []
        self._next_future = FakeFuture(result=[])
        self._processes = {1: FakeProcess()}
        FakeExecutor.instances.append(self)

    def submit(self, fn, *args):
        self.submitted.append((fn, args))
        return self._next_future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})


def _patch_executor(monkeypatch):
    FakeExecutor.instances = []
    monkeypatch.setattr("app.live.diarize_worker.ProcessPoolExecutor", FakeExecutor)
    return FakeExecutor


def test_diarize_returns_worker_result_on_success(monkeypatch, tmp_path):
    _patch_executor(monkeypatch)
    expected = [SpeakerSegment(start_ms=0, end_ms=1000, label="Speaker 1")]

    diarizer = ProcessIsolatedDiarizer(hf_token="fake", device="cpu")
    diarizer._ensure_executor()  # peek at the fake so we can rig its result
    executor = FakeExecutor.instances[0]
    executor._next_future = FakeFuture(result=expected)

    result = diarizer.diarize(tmp_path / "speaker.wav")
    assert result == expected


def test_executor_is_created_once_and_reused_across_calls(monkeypatch, tmp_path):
    _patch_executor(monkeypatch)
    diarizer = ProcessIsolatedDiarizer(hf_token="fake", device="cpu")

    diarizer.diarize(tmp_path / "a.wav")
    diarizer.diarize(tmp_path / "b.wav")

    assert len(FakeExecutor.instances) == 1


def test_broken_worker_returns_empty_list_and_respawns(monkeypatch, tmp_path):
    _patch_executor(monkeypatch)
    diarizer = ProcessIsolatedDiarizer(hf_token="fake", device="cpu")
    diarizer._ensure_executor()
    first_executor = FakeExecutor.instances[0]
    first_executor._next_future = FakeFuture(exception=BrokenExecutor("worker died"))

    result = diarizer.diarize(tmp_path / "speaker.wav")

    assert result == []
    assert first_executor.shutdown_calls == [{"wait": False, "cancel_futures": False}]
    assert all(p.killed for p in first_executor._processes.values())

    # Next call must spin up a fresh worker, not reuse the broken one.
    diarizer.diarize(tmp_path / "speaker.wav")
    assert len(FakeExecutor.instances) == 2


def test_timeout_returns_empty_list_and_respawns(monkeypatch, tmp_path):
    _patch_executor(monkeypatch)
    diarizer = ProcessIsolatedDiarizer(hf_token="fake", device="cpu", timeout_seconds=5.0)
    diarizer._ensure_executor()
    first_executor = FakeExecutor.instances[0]
    first_executor._next_future = FakeFuture(exception=FutureTimeoutError())

    result = diarizer.diarize(tmp_path / "speaker.wav")

    assert result == []
    assert first_executor.shutdown_calls == [{"wait": False, "cancel_futures": False}]
    assert all(p.killed for p in first_executor._processes.values())

    diarizer.diarize(tmp_path / "speaker.wav")
    assert len(FakeExecutor.instances) == 2


def test_shutdown_tears_down_executor(monkeypatch, tmp_path):
    _patch_executor(monkeypatch)
    diarizer = ProcessIsolatedDiarizer(hf_token="fake", device="cpu")
    diarizer.diarize(tmp_path / "speaker.wav")

    diarizer.shutdown()

    executor = FakeExecutor.instances[0]
    assert executor.shutdown_calls == [{"wait": False, "cancel_futures": False}]
    assert diarizer._executor is None
