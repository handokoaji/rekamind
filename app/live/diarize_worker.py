import logging
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

from app.diarization.diarizer import Diarizer, SpeakerSegment

logger = logging.getLogger(__name__)

_worker_diarizer: Diarizer | None = None


def _init_worker(hf_token: str, device: str) -> None:
    global _worker_diarizer
    _worker_diarizer = Diarizer(hf_token=hf_token, device=device)


def _diarize_in_worker(wav_path: str) -> list[SpeakerSegment]:
    return _worker_diarizer.diarize(Path(wav_path))


class ProcessIsolatedDiarizer:
    """Runs pyannote diarization in a separate OS process.

    pyannote/CUDA has been observed to crash the whole process natively
    (access violation, heap corruption) on certain degenerate audio rather
    than raise a catchable Python exception -- no amount of input validation
    in Diarizer.diarize() fully prevents this. Isolating it means a crash
    kills only this disposable worker; the meeting, recording, and rest of
    the app are unaffected, and the next tick just gets a fresh worker.

    The worker is created lazily and reused across calls -- loading the
    pipeline is the expensive part -- and only respawned after it actually
    breaks or hangs.
    """

    def __init__(self, hf_token: str, device: str, timeout_seconds: float = 30.0):
        self._hf_token = hf_token
        self._device = device
        self._timeout_seconds = timeout_seconds
        self._executor: ProcessPoolExecutor | None = None

    def _ensure_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=1, initializer=_init_worker, initargs=(self._hf_token, self._device),
            )
        return self._executor

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        executor = self._ensure_executor()
        future = executor.submit(_diarize_in_worker, str(wav_path))
        try:
            return future.result(timeout=self._timeout_seconds)
        except BrokenExecutor as exc:
            logger.warning("live diarize worker crashed (%s); respawning for the next tick", exc)
            self._executor = None
            executor.shutdown(wait=False)
            return []
        except FutureTimeoutError:
            logger.warning("live diarize worker timed out after %ss; respawning for the next tick", self._timeout_seconds)
            self._executor = None
            executor.shutdown(wait=False, cancel_futures=True)
            return []

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
