import wave
from unittest.mock import MagicMock

import numpy as np

from app.asr.openvino_backend import MAX_TRANSCRIBE_SECONDS, OpenVinoWhisperBackend, _load_audio_array


def _build_backend(monkeypatch):
    monkeypatch.setattr(
        "app.asr.openvino_backend.OVModelForSpeechSeq2Seq.from_pretrained",
        lambda *args, **kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend.WhisperProcessor.from_pretrained",
        lambda *args, **kwargs: MagicMock(),
    )
    return OpenVinoWhisperBackend()


def test_transcribe_maps_whisper_output_to_segments(monkeypatch, tmp_path):
    fake_model = MagicMock()
    fake_model.generate.return_value = MagicMock()

    fake_processor = MagicMock()
    fake_processor.return_value.input_features = MagicMock()
    fake_processor.batch_decode.return_value = ["Selamat pagi mari kita mulai"]

    monkeypatch.setattr(
        "app.asr.openvino_backend.OVModelForSpeechSeq2Seq.from_pretrained",
        lambda *args, **kwargs: fake_model,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend.WhisperProcessor.from_pretrained",
        lambda *args, **kwargs: fake_processor,
    )
    monkeypatch.setattr(
        "app.asr.openvino_backend._load_audio_array",
        lambda wav_path: (np.zeros(16000, dtype=np.float32), 16000),
    )

    backend = OpenVinoWhisperBackend()
    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path, language="id")

    # Verify language parameter is forwarded to model.generate()
    fake_model.generate.assert_called_once()
    assert fake_model.generate.call_args.kwargs["language"] == "id"

    assert len(segments) == 1
    assert segments[0].text == "Selamat pagi mari kita mulai"
    assert segments[0].start_ms == 0


def test_transcribe_chunks_audio_longer_than_the_window(monkeypatch, tmp_path):
    """The feature extractor hard-truncates each call to 30s -- transcribe()
    must slice longer audio into windows itself instead of silently returning
    a transcript of only the first window."""
    backend = _build_backend(monkeypatch)
    over_limit_seconds = MAX_TRANSCRIBE_SECONDS + 1
    monkeypatch.setattr(
        "app.asr.openvino_backend._load_audio_array",
        lambda wav_path: (np.zeros(int(16000 * over_limit_seconds), dtype=np.float32), 16000),
    )
    backend._processor.batch_decode.return_value = ["potongan"]

    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path)

    assert len(segments) == 2
    assert backend._model.generate.call_count == 2
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == int(MAX_TRANSCRIBE_SECONDS * 1000)
    assert segments[1].start_ms == int(MAX_TRANSCRIBE_SECONDS * 1000)
    assert segments[1].end_ms == int(over_limit_seconds * 1000)


def test_transcribe_allows_audio_at_exactly_the_limit(monkeypatch, tmp_path):
    backend = _build_backend(monkeypatch)
    backend._model.generate.return_value = MagicMock()
    backend._processor.batch_decode.return_value = ["ok"]
    monkeypatch.setattr(
        "app.asr.openvino_backend._load_audio_array",
        lambda wav_path: (np.zeros(int(16000 * MAX_TRANSCRIBE_SECONDS), dtype=np.float32), 16000),
    )

    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path)

    assert segments[0].text == "ok"


def test_load_audio_array_downmixes_and_resamples_native_device_format(tmp_path):
    """Capture writes the loopback device's native format (48kHz stereo); the
    Whisper feature extractor only accepts mono 16kHz."""
    wav_path = tmp_path / "speaker.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 2 * 48000)  # 1s of stereo silence

    audio, samplerate = _load_audio_array(wav_path)

    assert samplerate == 16000
    assert audio.ndim == 1
    assert abs(len(audio) - 16000) <= 1
