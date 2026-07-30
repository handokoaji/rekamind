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


def test_diarize_handles_non_contiguous_same_speaker(monkeypatch, tmp_path):
    """Verify that the same speaker appearing in non-contiguous turns gets consistent label."""
    fake_turn_1 = MagicMock(start=0.0, end=2.0)
    fake_turn_2 = MagicMock(start=2.0, end=4.0)
    fake_turn_3 = MagicMock(start=4.0, end=6.0)

    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_1, None, "SPEAKER_00"),  # Speaker A
        (fake_turn_2, None, "SPEAKER_01"),  # Speaker B
        (fake_turn_3, None, "SPEAKER_00"),  # Speaker A again (non-contiguous)
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
        SpeakerSegment(start_ms=2000, end_ms=4000, label="Speaker 2"),
        SpeakerSegment(start_ms=4000, end_ms=6000, label="Speaker 1"),
    ]
    # Both turn 1 and turn 3 should have "Speaker 1" label (same raw SPEAKER_00)
    assert segments[0].label == segments[2].label

def test_device_is_applied_to_pipeline(monkeypatch):
    """The device= arg used to be stored and never applied, so diarization
    silently always ran on CPU."""
    import torch

    fake_pipeline = MagicMock()
    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    Diarizer(hf_token="fake-token", device="cuda")

    fake_pipeline.to.assert_called_once_with(torch.device("cuda"))
