import queue
from pathlib import Path

import pytest

from app.audio.capture import AudioDeviceConfig, frame_callback, MicSpeakerRecorder
from app.audio.wav_writer import WavFileWriter


def test_frame_callback_writes_frames_to_writer(tmp_path):
    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer)
        frame_callback(frame, writer)

    import wave
    with wave.open(str(path), "rb") as wf:
        assert wf.getnframes() == 320


def test_config_defaults():
    config = AudioDeviceConfig()
    assert config.samplerate == 16000
    assert config.channels == 1


def test_stop_before_start_raises_error(tmp_path):
    """Calling stop() before start() should raise RuntimeError."""
    recorder = MicSpeakerRecorder(tmp_path / "mic.wav", tmp_path / "speaker.wav")
    with pytest.raises(RuntimeError, match="recorder was never started"):
        recorder.stop()


def test_start_twice_raises_error(tmp_path):
    """Calling start() twice should raise RuntimeError."""
    recorder = MicSpeakerRecorder(tmp_path / "mic.wav", tmp_path / "speaker.wav")
    # We can't actually call start() since we don't have pyaudiowpatch,
    # but we can manually set _pyaudio to simulate it
    recorder._pyaudio = object()  # Non-None to simulate already started
    with pytest.raises(RuntimeError, match="recorder is already started"):
        recorder.start()


@pytest.mark.hardware
def test_real_capture_start_stop(tmp_path):
    recorder = MicSpeakerRecorder(tmp_path / "mic.wav", tmp_path / "speaker.wav")
    recorder.start()
    mic_path, speaker_path = recorder.stop()
    assert mic_path.exists()
    assert speaker_path.exists()


def test_frame_callback_pushes_to_live_queue_without_blocking(tmp_path):
    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    live_queue = queue.Queue(maxsize=2)

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer, live_queue=live_queue, absolute_start_sample=4800)

    assert live_queue.get_nowait() == (frame, 4800)


def test_frame_callback_drops_frame_when_queue_full_instead_of_blocking(tmp_path):
    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    live_queue = queue.Queue(maxsize=1)
    live_queue.put_nowait(b"already-full")

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        # Must not raise or block even though the queue has no room.
        frame_callback(frame, writer, live_queue=live_queue)

    assert live_queue.get_nowait() == b"already-full"


def test_frame_callback_without_live_queue_still_works(tmp_path):
    path = tmp_path / "mic.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        frame_callback(frame, writer)  # no live_queue passed at all


def test_recorder_sample_counters_start_at_zero(tmp_path):
    """The absolute-sample tags handed to the live queue come from these counters,
    which must count every callback (dropped queue pushes included)."""
    recorder = MicSpeakerRecorder(tmp_path / "mic.wav", tmp_path / "speaker.wav")
    assert recorder._mic_samples_written == 0
    assert recorder._speaker_samples_written == 0
