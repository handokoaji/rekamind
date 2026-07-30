from unittest.mock import MagicMock

from app.diarization.diarizer import Diarizer, SpeakerSegment


def test_diarize_maps_pyannote_turns_to_speaker_segments(monkeypatch, tmp_path):
    fake_turn_1 = MagicMock(start=0.0, end=2.0)
    fake_turn_2 = MagicMock(start=2.0, end=4.5)

    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_1, None, "SPEAKER_00"),
        (fake_turn_2, None, "SPEAKER_01"),
    ]

    fake_pipeline = MagicMock()
    fake_pipeline.return_value = fake_annotation

    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    wav_path.touch()
    segments = diarizer.diarize(wav_path)

    assert segments == [
        SpeakerSegment(start_ms=0, end_ms=2000, label="Speaker 1"),
        SpeakerSegment(start_ms=2000, end_ms=4500, label="Speaker 2"),
    ]
