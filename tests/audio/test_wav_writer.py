import wave
from unittest.mock import patch, MagicMock

from app.audio.wav_writer import WavFileWriter


def test_writes_valid_wav_file(tmp_path):
    path = tmp_path / "out.wav"
    silence_frame = (0).to_bytes(2, "little", signed=True) * 160  # 10ms @16kHz mono

    with WavFileWriter(path, samplerate=16000, channels=1) as writer:
        writer.write_frames(silence_frame)
        writer.write_frames(silence_frame)

    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 320


def test_closes_file_handle_on_setup_failure(tmp_path):
    path = tmp_path / "out.wav"
    mock_wf = MagicMock()
    mock_wf.setnchannels.side_effect = ValueError("Invalid channels")

    with patch("wave.open", return_value=mock_wf):
        try:
            WavFileWriter(path, samplerate=16000, channels=1)
            assert False, "Expected ValueError to be raised"
        except ValueError:
            pass

    # Verify close() was called on the file handle
    mock_wf.close.assert_called_once()
