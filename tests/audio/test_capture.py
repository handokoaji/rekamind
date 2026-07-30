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
