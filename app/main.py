import asyncio
import tkinter as tk
import threading
from pathlib import Path

from app.asr.cuda_backend import CudaWhisperBackend
from app.asr.detect import detect_backend
from app.asr.openvino_backend import OpenVinoWhisperBackend
from app.config import get_settings
from app.diarization.diarizer import Diarizer
from app.pipeline.finalize import finalize_meeting
from app.storage.db import init_db, make_engine, make_session_factory
from app.summarization.groq_client import GroqSummarizer
from app.tray.icon import build_tray_icon
from app.ui.controller import RecorderController
from app.ui.window import MainWindow


def build_transcriber(backend_name: str):
    if backend_name == "cuda":
        return CudaWhisperBackend()
    if backend_name == "openvino":
        return OpenVinoWhisperBackend()
    return CudaWhisperBackend(device="cpu", compute_type="int8")


def _real_recorder(mic_path: Path, speaker_path: Path):
    from app.audio.capture import MicSpeakerRecorder
    return MicSpeakerRecorder(mic_path, speaker_path)


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    asyncio.run(init_db(engine))
    session_factory = make_session_factory(engine)

    backend_name = detect_backend(settings.asr_backend_override)
    transcriber = build_transcriber(backend_name)
    diarizer = Diarizer(hf_token=settings.hf_token)
    summarizer = GroqSummarizer(api_key=settings.groq_api_key)

    async def finalize_fn(session, meeting_id, meeting_title, meeting_date, mic_wav, speaker_wav):
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

    controller = RecorderController(
        session_factory=session_factory,
        recorder_factory=_real_recorder,
        finalize_fn=finalize_fn,
        recordings_dir=settings.recordings_dir,
    )

    root = tk.Tk()
    window = MainWindow(root, controller)

    def show_window():
        root.deiconify()

    def quit_app():
        root.quit()

    icon = build_tray_icon(on_show=show_window, on_quit=quit_app)

    threading.Thread(target=icon.run, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
