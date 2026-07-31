import asyncio
import logging
import queue
import shutil
import sys
import tkinter as tk
import threading
from pathlib import Path
from tkinter import messagebox

from app.asr.cuda_backend import FasterWhisperBackend
from app.asr.detect import detect_backend
from app.asr.openvino_backend import OpenVinoWhisperBackend
from app.config import get_settings
from app.diarization.diarizer import Diarizer
from app.live.diarize_worker import ProcessIsolatedDiarizer
from app.live.session import LiveSession
from app.live.vad import SpeechSegmenter, load_silero_vad_iterator
from app.logging_setup import configure_logging
from app.pipeline.recovery import recover_abandoned_meetings
from app.pipeline.summarize import summarize_and_export
from app.pipeline.transcribe import transcribe_and_diarize
from app.settings_store import is_dev_mode, load_packaged_config, save_packaged_config
from app.storage.db import init_db, make_engine, make_session_factory
from app.summarization.docx_export import build_docx_filename
from app.summarization.groq_client import GroqSummarizer
from app.tray.icon import build_tray_icon
from app.ui.controller import RecorderController
from app.ui.setup_wizard import SetupWizard
from app.ui.window import MainWindow

logger = logging.getLogger(__name__)


def check_ffmpeg_available() -> bool:
    """Diarization (pyannote/torchaudio) needs FFmpeg's shared libraries on
    PATH to decode audio. Missing FFmpeg doesn't stop the app — capture, ASR,
    and summarization all work without it — only diarization will fail later,
    so we warn once at startup instead of silently installing anything."""
    if shutil.which("ffmpeg") is not None:
        return True
    print(
        "WARNING: ffmpeg tidak ditemukan di PATH. Speaker diarization tidak akan "
        "berfungsi. Pasang dengan: winget install ffmpeg",
        file=sys.stderr,
    )
    return False


def build_transcriber(backend_name: str):
    if backend_name == "cuda":
        # int8 (not the class default float32): large-v3 in float32 is the
        # single biggest RAM/VRAM cost in the app once loaded (~6-10GB), and it
        # stays resident for the rest of the app run. int8 uses CUDA's DP4A
        # path (supported from compute capability 6.1 onward, e.g. GTX 1080
        # Ti) rather than float16, which faster-whisper already avoids here
        # because it silently misbehaves on Pascal-generation GPUs.
        return FasterWhisperBackend(compute_type="int8")
    if backend_name == "openvino":
        return OpenVinoWhisperBackend()
    return FasterWhisperBackend(device="cpu", compute_type="int8")


def build_live_transcriber(backend_name: str):
    """Small model for live preview - same backend family as the batch
    transcriber, just a lighter size so it keeps up in near-real-time."""
    if backend_name == "cuda":
        return FasterWhisperBackend(model_size="small", device="cuda", compute_type="float32")
    if backend_name == "openvino":
        return OpenVinoWhisperBackend(model_size="small")
    return FasterWhisperBackend(model_size="small", device="cpu", compute_type="int8")


def query_loopback_format() -> tuple[int, int]:
    """Native (samplerate, channels) of the WASAPI loopback device -- a
    machine-level property, so it is read independently of any recorder
    instance (the live session is built before the recorder exists)."""
    import pyaudiowpatch as pyaudio

    pa = pyaudio.PyAudio()
    try:
        info = pa.get_default_wasapi_loopback()
        return int(info["defaultSampleRate"]), int(info["maxInputChannels"])
    finally:
        pa.terminate()


def build_models(backend_name: str, settings):
    """(transcriber, diarizer, summarizer). On a backend load failure BOTH the
    transcriber and the diarizer fall back to CPU: telling the diarizer "cuda"
    after the GPU already failed to load just crashes it later (spec §9)."""
    try:
        transcriber = build_transcriber(backend_name)
        effective_device = "cuda" if backend_name == "cuda" else "cpu"
    except Exception as exc:
        logger.warning("failed to load %s backend (%s), falling back to CPU", backend_name, exc)
        transcriber = build_transcriber("cpu")
        effective_device = "cpu"
    return (
        transcriber,
        Diarizer(hf_token=settings.hf_token, device=effective_device),
        GroqSummarizer(api_key=settings.groq_api_key),
    )


recorder_queues: dict = {"mic": None, "speaker": None}

# Heavy batch models are loaded on the first Transkrip/Ringkasan click, not at
# startup: the window must appear at once, and a meeting sitting in Riwayat
# waiting to be processed shouldn't cost anything until clicked.
_models = None
_models_lock = threading.Lock()


def load_models(backend_name: str, settings):
    """Thread-safe lazy singleton. Transkrip/Ringkasan on two different meetings
    may run at the same time (spec §6, "boleh bersamaan"); without the lock both
    threads see `_models is None` and each builds its own large-v3 + pyannote
    pair, which is a straight path to CUDA OOM."""
    global _models
    with _models_lock:
        if _models is None:
            _models = build_models(backend_name, settings)
        return _models


def _real_recorder(mic_path: Path, speaker_path: Path):
    from app.audio.capture import MicSpeakerRecorder
    return MicSpeakerRecorder(
        mic_path, speaker_path,
        mic_queue=recorder_queues["mic"], speaker_queue=recorder_queues["speaker"],
    )


def run_first_run_wizard_if_needed() -> bool:
    """Returns False if the app must not proceed (packaged mode, no config
    yet, and the user closed the wizard without submitting)."""
    if is_dev_mode() or load_packaged_config() is not None:
        return True
    result = SetupWizard(parent=None).run()
    return result is not None


def _handle_startup_db_error(exc: Exception) -> bool:
    """Returns True if the user updated settings via the wizard and startup
    should retry; False if they declined and the app should just exit."""
    root = tk.Tk()
    root.withdraw()
    reopen = messagebox.askyesno(
        "Meeting Recorder - Error",
        f"Tidak bisa konek ke database: {exc}\n\nBuka Pengaturan sekarang?",
    )
    if not reopen:
        root.destroy()
        return False
    result = SetupWizard(parent=None).run()
    root.destroy()
    if result is None:
        return False
    save_packaged_config(result)
    return True


def main() -> None:
    configure_logging()
    if not run_first_run_wizard_if_needed():
        return
    get_settings.cache_clear()
    settings = get_settings()
    check_ffmpeg_available()
    engine = make_engine(settings.database_url)
    try:
        asyncio.run(init_db(engine))
    except Exception as exc:
        if not _handle_startup_db_error(exc):
            return
        get_settings.cache_clear()
        settings = get_settings()
        engine = make_engine(settings.database_url)
        asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    recovered = asyncio.run(recover_abandoned_meetings(session_factory))
    if recovered:
        logger.info("recovered %d meeting(s) orphaned by a previous crash: %s", len(recovered), recovered)

    backend_name = detect_backend(settings.asr_backend_override)

    async def transcribe_fn(meeting_id, mic_wav, speaker_wav):
        transcriber, diarizer, _summarizer = load_models(backend_name, settings)
        await transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav, transcriber, diarizer)

    async def summarize_fn(meeting_id, meeting_title, meeting_date):
        _transcriber, _diarizer, summarizer = load_models(backend_name, settings)
        docx_filename = build_docx_filename(meeting_date, meeting_title)
        docx_path = settings.recordings_dir / str(meeting_id) / docx_filename
        await summarize_and_export(session_factory, meeting_id, meeting_title, meeting_date, docx_path, summarizer)

    # Same lazy-singleton deal as load_models() above: the small live model and the
    # live diarizer are built on the first "Mulai Rekam", not at startup (the window
    # must appear at once), then reused for every later meeting in this app run.
    # A load failure propagates to the controller, which starts the recording
    # without live preview (spec §5) and retries the load on the next meeting.
    live_transcriber = None
    live_diarizer = None

    window_ref: dict = {}  # populated below once `window` exists; closures need this indirection

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        nonlocal live_transcriber, live_diarizer
        if live_transcriber is None:
            live_transcriber = build_live_transcriber(backend_name)
        if live_diarizer is None:
            # Process-isolated (not the plain Diarizer main.py uses for the batch
            # pass): pyannote/CUDA has been observed to crash the whole process
            # natively on degenerate live audio, and no input validation in
            # Diarizer.diarize() has fully prevented it. A worker crash here only
            # loses one relabel tick, not the meeting in progress.
            live_diarizer = ProcessIsolatedDiarizer(
                hf_token=settings.hf_token, device="cuda" if backend_name == "cuda" else "cpu",
            )
        mic_queue: "queue.Queue" = queue.Queue(maxsize=200)
        speaker_queue: "queue.Queue" = queue.Queue(maxsize=200)
        # The loopback device records at its native format (typically 48kHz
        # stereo); the live pipeline needs to know so it can convert to 16kHz mono.
        speaker_samplerate, speaker_channels = query_loopback_format()
        session = LiveSession(
            mic_transcriber=live_transcriber,
            speaker_transcriber=live_transcriber,
            diarizer=live_diarizer,
            segmenter_factory=lambda: SpeechSegmenter(load_silero_vad_iterator()),
            mic_wav_path=mic_wav_path,
            speaker_wav_path=speaker_wav_path,
            scratch_dir=scratch_dir,
            mic_queue=mic_queue,
            speaker_queue=speaker_queue,
            diarize_interval_seconds=8.0,
            on_update=window_ref["window"].push_live_event,
            speaker_samplerate=speaker_samplerate,
            speaker_channels=speaker_channels,
            session_factory=session_factory,
        )
        # MicSpeakerRecorder needs these same queues to actually feed audio in;
        # stash them so _real_recorder (above) can pick them up for this meeting.
        recorder_queues["mic"] = mic_queue
        recorder_queues["speaker"] = speaker_queue
        return session

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        transcribe_fn=transcribe_fn,
        summarize_fn=summarize_fn,
        recordings_dir=settings.recordings_dir,
        live_session_factory=live_session_factory,
        device_id=settings.device_id,
        device_label=settings.device_label,
    )

    root = tk.Tk()
    window = MainWindow(root, controller)
    window_ref["window"] = window

    def show_window():
        root.after(0, root.deiconify)

    def quit_app():
        root.after(0, root.quit)

    # X button hides to tray instead of killing the app; "Buka Dashboard" reopens.
    root.protocol("WM_DELETE_WINDOW", root.withdraw)

    icon = build_tray_icon(on_show=show_window, on_quit=quit_app)

    threading.Thread(target=icon.run, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
