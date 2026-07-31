import logging
import queue
from dataclasses import dataclass
from pathlib import Path

from app.audio.wav_writer import WavFileWriter

logger = logging.getLogger(__name__)


@dataclass
class AudioDeviceConfig:
    samplerate: int = 16000
    channels: int = 1


def frame_callback(
    frames: bytes,
    writer: WavFileWriter,
    live_queue: "queue.Queue | None" = None,
    absolute_start_sample: int = 0,
) -> None:
    writer.write_frames(frames)
    if live_queue is not None:
        try:
            # Tag every chunk with its absolute position in the recording. The WAV
            # write above never drops, but the queue below does; without the tag,
            # a single drop would shift every later live timestamp relative to the
            # diarization of the complete WAV they get merged against.
            live_queue.put_nowait((frames, absolute_start_sample))
        except queue.Full:
            pass  # live preview is best-effort; the WAV write above already happened


class MicSpeakerRecorder:
    """Captures mic input and WASAPI speaker loopback in parallel to two WAV files.

    Real device I/O uses pyaudiowpatch (Windows-only WASAPI loopback support).
    Import is deferred into start() so this module can be imported and the
    frame_callback logic tested on any platform without pyaudiowpatch installed.
    """

    def __init__(
        self,
        mic_path: Path,
        speaker_path: Path,
        config: AudioDeviceConfig | None = None,
        mic_queue: "queue.Queue | None" = None,
        speaker_queue: "queue.Queue | None" = None,
    ):
        self._mic_path = mic_path
        self._speaker_path = speaker_path
        self._config = config or AudioDeviceConfig()
        self._mic_queue = mic_queue
        self._speaker_queue = speaker_queue
        self._pyaudio = None
        self._mic_stream = None
        self._speaker_stream = None
        self._mic_writer: WavFileWriter | None = None
        self._speaker_writer: WavFileWriter | None = None
        # Counted per audio callback, whether or not the live-queue push succeeds.
        self._mic_samples_written = 0
        self._speaker_samples_written = 0

    def start(self) -> None:
        if self._pyaudio is not None:
            raise RuntimeError("recorder is already started")

        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio.PyAudio()
        # mic.wav has shown up fully empty (device opened, zero callbacks ever
        # fired) with no exception anywhere -- logging which device PortAudio
        # actually picked makes a wrong/disabled default mic diagnosable from
        # the log instead of only discovered after the meeting ends.
        try:
            default_mic = self._pyaudio.get_default_input_device_info()
            logger.info("mic capture device: %s (index %s)", default_mic["name"], default_mic["index"])
        except Exception as exc:
            logger.warning("no default input (mic) device found: %s", exc)
        self._mic_writer = WavFileWriter(self._mic_path, self._config.samplerate, self._config.channels)

        default_speakers = self._pyaudio.get_default_wasapi_loopback()
        speaker_samplerate = int(default_speakers["defaultSampleRate"])
        speaker_channels = default_speakers["maxInputChannels"]
        self._speaker_writer = WavFileWriter(self._speaker_path, speaker_samplerate, speaker_channels)

        def mic_stream_callback(in_data, frame_count, time_info, status):
            # Capture the count BEFORE incrementing: the tag means "samples
            # written before this chunk".
            frame_callback(in_data, self._mic_writer, self._mic_queue, self._mic_samples_written)
            self._mic_samples_written += frame_count
            return (None, pyaudio.paContinue)

        def speaker_stream_callback(in_data, frame_count, time_info, status):
            frame_callback(in_data, self._speaker_writer, self._speaker_queue, self._speaker_samples_written)
            self._speaker_samples_written += frame_count
            return (None, pyaudio.paContinue)

        self._mic_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=self._config.channels,
            rate=self._config.samplerate, input=True,
            stream_callback=mic_stream_callback,
        )
        self._speaker_stream = self._pyaudio.open(
            format=pyaudio.paInt16, channels=speaker_channels,
            rate=speaker_samplerate, input=True,
            input_device_index=default_speakers["index"],
            stream_callback=speaker_stream_callback,
        )
        self._mic_stream.start_stream()
        self._speaker_stream.start_stream()

    def stop(self) -> tuple[Path, Path]:
        if self._pyaudio is None:
            raise RuntimeError("recorder was never started")

        for stream in (self._mic_stream, self._speaker_stream):
            if stream is not None:
                stream.stop_stream()
                stream.close()
        if self._pyaudio is not None:
            self._pyaudio.terminate()
        if self._mic_writer is not None:
            self._mic_writer.close()
        if self._speaker_writer is not None:
            self._speaker_writer.close()
        return self._mic_path, self._speaker_path
