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
    for _ in range(3):
        results.extend(segmenter.process_chunk(_window()))

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
    assert segmenter.process_chunk(half) == []  # not enough for one window yet
    assert len(calls) == 0
    assert segmenter.process_chunk(half) == []  # now exactly one window's worth
    assert len(calls) == 1


def test_segmenter_returns_nothing_outside_speech():
    def fake_vad_iterator(tensor, return_seconds=False):
        return None

    segmenter = SpeechSegmenter(vad_iterator=fake_vad_iterator, samplerate=16000)
    assert segmenter.process_chunk(_window()) == []


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
