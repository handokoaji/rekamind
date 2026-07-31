import wave
from unittest.mock import MagicMock

from app.diarization.diarizer import Diarizer, SpeakerSegment


def _write_silent_wav(path, samplerate=16000, channels=1, num_frames=32000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes((0).to_bytes(2, "little", signed=True) * num_frames * channels)


def _fake_output(fake_annotation):
    """pyannote.audio >= 4 wraps the Annotation in a DiarizeOutput with an
    `exclusive_speaker_diarization` attribute; mirror that shape here."""
    output = MagicMock(spec=["exclusive_speaker_diarization"])
    output.exclusive_speaker_diarization = fake_annotation
    return output


def test_diarize_maps_pyannote_turns_to_speaker_segments(monkeypatch, tmp_path):
    fake_turn_1 = MagicMock(start=0.0, end=2.0)
    fake_turn_2 = MagicMock(start=2.0, end=4.5)

    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_1, None, "SPEAKER_00"),
        (fake_turn_2, None, "SPEAKER_01"),
    ]

    fake_pipeline = MagicMock()
    fake_pipeline.return_value = _fake_output(fake_annotation)

    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    _write_silent_wav(wav_path)
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
    fake_pipeline.return_value = _fake_output(fake_annotation)

    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    _write_silent_wav(wav_path)
    segments = diarizer.diarize(wav_path)

    assert segments == [
        SpeakerSegment(start_ms=0, end_ms=2000, label="Speaker 1"),
        SpeakerSegment(start_ms=2000, end_ms=4000, label="Speaker 2"),
        SpeakerSegment(start_ms=4000, end_ms=6000, label="Speaker 1"),
    ]
    # Both turn 1 and turn 3 should have "Speaker 1" label (same raw SPEAKER_00)
    assert segments[0].label == segments[2].label

def test_diarize_passes_waveform_dict_not_path(monkeypatch, tmp_path):
    """diarize() must not hand the pipeline a raw path: that decode route
    goes through torchcodec, which has repeatedly broken across otherwise
    unrelated torch/FFmpeg version changes."""
    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = []

    fake_pipeline = MagicMock()
    fake_pipeline.return_value = _fake_output(fake_annotation)

    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    _write_silent_wav(wav_path, samplerate=16000, channels=1, num_frames=32000)
    diarizer.diarize(wav_path)

    fake_pipeline.assert_called_once()
    (call_arg,), _ = fake_pipeline.call_args
    assert isinstance(call_arg, dict)
    assert set(call_arg.keys()) == {"waveform", "sample_rate"}
    assert call_arg["sample_rate"] == 16000
    assert call_arg["waveform"].shape[0] == 1  # (channel, time), mono


def test_diarize_returns_empty_list_for_missing_file(monkeypatch, tmp_path):
    """A live meeting's first diarize tick can fire before the speaker WAV
    has any frames written -- must not blow up, just report no speakers yet."""
    fake_pipeline = MagicMock()
    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    assert diarizer.diarize(tmp_path / "does-not-exist.wav") == []
    fake_pipeline.assert_not_called()


def test_diarize_returns_empty_list_for_header_only_file(monkeypatch, tmp_path):
    """WavFileWriter creates the file on open but only writes the RIFF header
    once the first frame arrives; a header-only/empty file isn't diarizable yet."""
    fake_pipeline = MagicMock()
    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    empty_wav = tmp_path / "speaker.wav"
    empty_wav.touch()
    assert diarizer.diarize(empty_wav) == []
    fake_pipeline.assert_not_called()


def test_diarize_returns_empty_list_for_sub_second_audio(monkeypatch, tmp_path):
    """A live meeting's early diarize ticks can catch the speaker WAV with only
    a fraction of a second of real audio. Feeding pyannote's pooling layer a
    near-empty window has been observed to crash the process natively (access
    violation / heap corruption) on CUDA rather than raise a Python exception
    -- skip it instead of risking that."""
    fake_pipeline = MagicMock()
    monkeypatch.setattr(
        "app.diarization.diarizer.Pipeline.from_pretrained",
        lambda *args, **kwargs: fake_pipeline,
    )

    diarizer = Diarizer(hf_token="fake-token")
    wav_path = tmp_path / "speaker.wav"
    _write_silent_wav(wav_path, samplerate=16000, num_frames=4000)  # 0.25s
    assert diarizer.diarize(wav_path) == []
    fake_pipeline.assert_not_called()


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
