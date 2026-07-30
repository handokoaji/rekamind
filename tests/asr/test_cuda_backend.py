from unittest.mock import MagicMock

import pytest

from app.asr.cuda_backend import FasterWhisperBackend


def test_transcribe_maps_faster_whisper_segments(monkeypatch, tmp_path):
    fake_segment_1 = MagicMock(start=0.0, end=1.2, text=" Selamat pagi")
    fake_segment_2 = MagicMock(start=1.2, end=2.5, text=" mari kita mulai")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment_1, fake_segment_2], MagicMock())

    monkeypatch.setattr(
        "app.asr.cuda_backend.WhisperModel",
        lambda *args, **kwargs: fake_model,
    )

    backend = FasterWhisperBackend()
    wav_path = tmp_path / "audio.wav"
    wav_path.touch()
    segments = backend.transcribe(wav_path, language="id")

    fake_model.transcribe.assert_called_once_with(str(wav_path), language="id")
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1200
    assert segments[0].text == "Selamat pagi"
    assert segments[1].text == "mari kita mulai"
