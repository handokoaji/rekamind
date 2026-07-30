import asyncio
import queue
import shutil
import sys
import tkinter as tk
import threading
from pathlib import Path

from app.asr.cuda_backend import FasterWhisperBackend
from app.asr.detect import detect_backend
from app.asr.openvino_backend import OpenVinoWhisperBackend
from app.config import get_settings
from app.diarization.diarizer import Diarizer
from app.live.session import LiveSession
from app.live.vad import SpeechSegmenter, load_silero_vad_iterator
from app.pipeline.finalize import finalize_meeting
from app.storage.db import init_db, make_engine, make_session_factory
from app.summarization.groq_client import GroqSummarizer
from app.tray.icon import build_tray_icon
from app.ui.controller import RecorderController
from app.ui.window import MainWindow


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
        return FasterWhisperBackend()
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


def build_models(backend_name: str, settings):
    """(transcriber, diarizer, summarizer). On a backend load failure BOTH the
    transcriber and the diarizer fall back to CPU: telling the diarizer "cuda"
    after the GPU already failed to load just crashes it later (spec §9)."""
    try:
        transcriber = build_transcriber(backend_name)
        effective_device = "cuda" if backend_name == "cuda" else "cpu"
    except Exception as exc:
        print(
            f"WARNING: failed to load {backend_name} backend ({exc}), falling back to CPU",
            file=sys.stderr,
        )
        transcriber = build_transcriber("cpu")
        effective_device = "cpu"
    return (
        transcriber,
        Diarizer(hf_token=settings.hf_token, device=effective_device),
        GroqSummarizer(api_key=settings.groq_api_key),
    )


recorder_queues: dict = {"mic": None, "speaker": None}


def _real_recorder(mic_path: Path, speaker_path: Path):
    from app.audio.capture import MicSpeakerRecorder
    return MicSpeakerRecorder(
        mic_path, speaker_path,
        mic_queue=recorder_queues["mic"], speaker_queue=recorder_queues["speaker"],
    )


def main() -> None:
    settings = get_settings()
    check_ffmpeg_available()
    engine = make_engine(settings.database_url)
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    backend_name = detect_backend(settings.asr_backend_override)

    # Heavy models are loaded on the first finalize, not at startup: spec §2 wants
    # them resident only for the batch pass, and the window must appear at once.
    models = None

    def load_models():
        nonlocal models
        if models is None:
            models = build_models(backend_name, settings)
        return models

    async def finalize_fn(session, meeting_id, meeting_title, meeting_date, mic_wav, speaker_wav):
        transcriber, diarizer, summarizer = load_models()
        docx_path = settings.recordings_dir / str(meeting_id) / "mom.docx"
        return await finalize_meeting(
            session=session,
            meeting_id=meeting_id,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            mic_wav=mic_wav,
            speaker_wav=speaker_wav,
            transcriber=transcriber,
            diarizer=diarizer,
            summarizer=summarizer,
            docx_output_path=docx_path,
        )

    live_transcriber = None
    try:
        live_transcriber = build_live_transcriber(backend_name)
    except Exception as exc:
        print(f"WARNING: live preview model failed to load ({exc}); live preview disabled this session", file=sys.stderr)

    window_ref: dict = {}  # populated below once `window` exists; closures need this indirection

    def live_session_factory(mic_wav_path, speaker_wav_path, scratch_dir):
        if live_transcriber is None:
            raise RuntimeError("live preview model not loaded")
        mic_queue: "queue.Queue" = queue.Queue(maxsize=200)
        speaker_queue: "queue.Queue" = queue.Queue(maxsize=200)
        live_diarizer = Diarizer(hf_token=settings.hf_token, device="cuda" if backend_name == "cuda" else "cpu")
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
        )
        # MicSpeakerRecorder needs these same queues to actually feed audio in;
        # stash them so _real_recorder (above) can pick them up for this meeting.
        recorder_queues["mic"] = mic_queue
        recorder_queues["speaker"] = speaker_queue
        return session

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        finalize_fn=finalize_fn,
        recordings_dir=settings.recordings_dir,
        live_session_factory=live_session_factory,
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
