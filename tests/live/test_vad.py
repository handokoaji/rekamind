from app.live.vad import SpeechSegment, SpeechSegmenter

WINDOW_SAMPLES = 512
WINDOW_BYTES = WINDOW_SAMPLES * 2  # int16 mono


def _window(value: int = 1) -> bytes:
    return value.to_bytes(2, "little", signed=True) * WINDOW_SAMPLES


def test_segmenter_emits_segment_spanning_start_to_end_windows():
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        if len(calls) == 1:
            return {"start": 137}
        if len(calls) == 3:
            return {"end": 1536}
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)

    results = []
    for i in range(3):
        results.extend(segmenter.process_chunk(_window(), i * WINDOW_SAMPLES))

    assert len(results) == 1
    assert isinstance(results[0], SpeechSegment)
    assert results[0].start_sample == 137
    assert len(results[0].audio) == WINDOW_BYTES * 3


def test_segmenter_buffers_partial_chunks_across_calls():
    """Chunks smaller than one VAD window must accumulate, not be dropped."""
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)

    half = _window()[: WINDOW_BYTES // 2]
    assert segmenter.process_chunk(half, 0) == []  # not enough for one window yet
    assert len(calls) == 0
    assert segmenter.process_chunk(half, WINDOW_SAMPLES // 2) == []  # now one window's worth
    assert len(calls) == 1


def test_segmenter_returns_nothing_outside_speech():
    def fake_vad_iterator(tensor, return_seconds=False):
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)
    assert segmenter.process_chunk(_window(), 0) == []


def test_segment_start_follows_absolute_position_after_a_dropped_chunk():
    """A chunk lost to a full live queue must not shift later timestamps: the
    absolute sample tag, not a self-incremented counter, is the source of truth."""
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        # VADIterator reports positions in its OWN space: it has only seen two
        # windows, so speech starting on its 2nd window is "512" to it.
        if len(calls) == 2:
            return {"start": 512}
        if len(calls) == 3:
            return {"end": 1024}
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)

    # Chunks 0..9 were captured but only #0 and #9 reached the live queue.
    assert segmenter.process_chunk(_window(), 0) == []
    assert segmenter.process_chunk(_window(), 9 * WINDOW_SAMPLES) == []
    results = segmenter.process_chunk(_window(), 10 * WINDOW_SAMPLES)

    assert len(results) == 1
    # Speech started on the window tagged 9*512, not on a self-counted "512".
    assert results[0].start_sample == 9 * WINDOW_SAMPLES


def test_segmenter_force_closes_a_segment_that_exceeds_the_max_duration():
    """A stuck-triggered VAD (start, then never an end) must not buffer forever."""
    calls = []

    def fake_vad_iterator(tensor, return_seconds=False):
        calls.append(tensor)
        return {"start": 0} if len(calls) == 1 else None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)
    max_windows = SpeechSegmenter.MAX_SEGMENT_SECONDS * 16000 // WINDOW_SAMPLES

    results = []
    for i in range(max_windows + 2):
        results.extend(segmenter.process_chunk(_window(), i * WINDOW_SAMPLES))

    assert len(results) == 1, "expected exactly one force-closed segment"
    assert results[0].start_sample == 0
    assert len(results[0].audio) <= SpeechSegmenter.MAX_SEGMENT_SECONDS * 16000 * 2
    # Audio is continued, not discarded: the next segment picks up where this ended.
    assert segmenter._speech_start_sample == max_windows * WINDOW_SAMPLES
    assert len(segmenter._speech_buffer) > 0


def test_vad_module_importable_without_torch_at_module_level():
    """Verify that app.live.vad can be imported without torch being loaded at import time.

    Only _bytes_to_tensor (called by load_silero_vad_iterator) should import torch,
    not the module-level imports. This allows the module to be imported on systems
    without torch installed.
    """
    import app.live.vad as vad_module

    # torch should not be in the module-level namespace
    assert "torch" not in dir(vad_module), \
        "torch should not be imported at module level; it should only be imported inside _bytes_to_tensor"


def test_load_silero_vad_iterator_never_shares_the_model(monkeypatch):
    """The model (not the iterator) holds the VAD's mutable trigger state
    (_state/_context), mutated on every call. Mic and speaker run concurrently
    on separate threads; a shared model there is a data race that corrupts VAD
    state and crashes the process natively. Every call must get its own model."""
    import app.live.vad as vad_module

    loads = []

    class _FakeSileroModule:
        @staticmethod
        def load_silero_vad():
            loads.append(1)
            return object()

        class VADIterator:
            def __init__(self, model, sampling_rate=16000):
                self.model = model

    monkeypatch.setitem(__import__("sys").modules, "silero_vad", _FakeSileroModule)

    first = vad_module.load_silero_vad_iterator()
    second = vad_module.load_silero_vad_iterator()

    assert len(loads) == 2  # model loaded fresh each time...
    assert first is not second  # ...iterator built fresh each time
    assert first.model is not second.model  # ...and never shares mutable VAD state
