import time
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


def test_write_frames_flushes_so_concurrent_reader_sees_data(tmp_path):
    path = tmp_path / "live.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160
    writer = WavFileWriter(path, samplerate=16000, channels=1)
    writer.write_frames(frame)

    # Second, independent read handle on the SAME still-open file.
    # First write always flushes (due to _last_flush_time initialization).
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 160

    writer.close()


def test_rapid_writes_only_flush_once(tmp_path):
    """Verify that two rapid writes within the flush interval only flush once."""
    path = tmp_path / "rapid.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160

    fake_time = [0.0]  # Use a list to allow modification in nested scope

    def fake_monotonic():
        return fake_time[0]

    with patch("app.audio.wav_writer.time.monotonic", side_effect=fake_monotonic):
        with patch.object(WavFileWriter, "__init__", return_value=None) as mock_init:
            writer = WavFileWriter.__new__(WavFileWriter)
            writer._wf = MagicMock()
            writer._flush_interval_seconds = 1.0
            writer._last_flush_time = -1.0  # Set to past so first write flushes

            with patch.object(writer._wf, "_patchheader") as mock_patch:
                # First write at time 0 flushes
                writer.write_frames(frame)
                assert mock_patch.call_count == 1

                # Advance time by 0.5 seconds (still within 1.0 second interval)
                fake_time[0] += 0.5
                writer.write_frames(frame)
                # Should NOT flush because interval hasn't passed
                assert mock_patch.call_count == 1


def test_writes_flush_after_interval_passes(tmp_path):
    """Verify that after the throttle interval passes, subsequent writes do flush."""
    path = tmp_path / "interval.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160

    fake_time = [0.0]

    def fake_monotonic():
        return fake_time[0]

    with patch("app.audio.wav_writer.time.monotonic", side_effect=fake_monotonic):
        writer = WavFileWriter.__new__(WavFileWriter)
        writer._wf = MagicMock()
        writer._flush_interval_seconds = 1.0
        writer._last_flush_time = -1.0

        with patch.object(writer._wf, "_patchheader") as mock_patch:
            # First write at time 0 flushes
            writer.write_frames(frame)
            assert mock_patch.call_count == 1

            # Advance time by 1.1 seconds (past the 1.0 second interval)
            fake_time[0] += 1.1
            writer.write_frames(frame)
            # Should flush because interval has passed
            assert mock_patch.call_count == 2


def test_close_always_flushes_regardless_of_throttle(tmp_path):
    """Verify that close() always flushes even if the interval hasn't passed."""
    path = tmp_path / "close_flush.wav"
    frame = (0).to_bytes(2, "little", signed=True) * 160

    fake_time = [0.0]

    def fake_monotonic():
        return fake_time[0]

    with patch("app.audio.wav_writer.time.monotonic", side_effect=fake_monotonic):
        # Use a very long interval to ensure close() is not affected by throttling
        writer = WavFileWriter(path, samplerate=16000, channels=1, flush_interval_seconds=10.0)

        with patch.object(writer._wf, "_patchheader") as mock_patch:
            writer.write_frames(frame)
            assert mock_patch.call_count == 1

            # close() should flush again even though interval hasn't passed
            writer.close()
            assert mock_patch.call_count == 2

    # Verify file is valid
    with wave.open(str(path), "rb") as reader:
        assert reader.getnframes() == 160
