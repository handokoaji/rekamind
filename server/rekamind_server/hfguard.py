"""Cut off a model download that has gone slow, so it retries on a fresh connection.

Why: Hugging Face serves model files from a CDN host that resolves to about ten addresses. On a real server one of them
answered at 0.1 MB/s while the others gave 27 MB/s. `huggingface_hub` only times out when *no* byte arrives for ten
seconds, and a slow node keeps trickling bytes, so a 3 GB Whisper model (or a 26 MB pyannote file) sat at a crawl on the
same pooled connection for as long as the process lived, and the first transcription never finished.

What: every large download response is wrapped so that, once it has run for `GRACE` seconds, a rate below the minimum
over the last `WINDOW` seconds raises a timeout. `huggingface_hub` already retries a timed-out download by resuming it,
and the dropped connection means the retry resolves the host again and usually lands on a healthy node.
Only plain HTTP downloads are covered, which is why the images set HF_HUB_DISABLE_XET=1.
"""
from __future__ import annotations

import collections
import functools
import logging
import time
from collections.abc import Callable

log = logging.getLogger("rekamind.hfguard")

MIN_GUARDED_BYTES = 20_000_000  # small files (configs, tokenizers) are not worth guarding
GRACE = 12.0  # seconds a download may take to get going
WINDOW = 10.0  # the rate is measured over this many seconds


def _httpx():
    try:
        import httpx2 as httpx  # huggingface_hub 2.x
    except ImportError:
        import httpx  # huggingface_hub 1.x
    return httpx


try:
    _Base = _httpx().SyncByteStream  # httpx insists that a response's stream is one of these
except ImportError:  # no httpx at all: install() will not find huggingface_hub either
    _Base = object


class GuardedStream(_Base):
    """Wraps an httpx byte stream and raises `ReadTimeout` when the download rate stays under `min_bps`."""

    def __init__(self, inner, min_bps: float, clock: Callable[[], float] = time.monotonic):
        self._inner, self._min_bps, self._clock = inner, min_bps, clock

    def __iter__(self):
        start = self._clock()
        total = 0
        marks: collections.deque[tuple[float, int]] = collections.deque([(start, 0)])
        for chunk in self._inner:
            now = self._clock()
            total += len(chunk)
            marks.append((now, total))
            while len(marks) > 1 and now - marks[0][0] > WINDOW:
                marks.popleft()
            span = now - marks[0][0]
            if now - start >= GRACE and span >= WINDOW * 0.8:
                rate = (total - marks[0][1]) / span
                if rate < self._min_bps:
                    log.warning("model download too slow (%.2f MB/s over %.0f s); dropping the connection to retry",
                                rate / 1e6, span)
                    self.close()
                    raise _httpx().ReadTimeout(f"download too slow: {rate / 1e6:.2f} MB/s")
            yield chunk

    def close(self) -> None:
        self._inner.close()


def _guard_response(response, *, min_bps: float) -> None:
    try:
        length = int(response.headers.get("content-length", "0"))
    except ValueError:
        return
    if length >= MIN_GUARDED_BYTES:
        response.stream = GuardedStream(response.stream, min_bps)


def install(min_mbps: float = 0.5) -> bool:
    """Make `huggingface_hub` use a client with the guard. Returns False when it cannot (or is switched off with 0)."""
    if min_mbps <= 0:
        return False
    try:
        from huggingface_hub import set_client_factory
        from huggingface_hub.utils._http import default_client_factory
    except Exception:  # an older huggingface_hub (requests based) or none at all: nothing to guard
        log.debug("huggingface_hub client factory not available; download guard not installed", exc_info=True)
        return False
    hook = functools.partial(_guard_response, min_bps=min_mbps * 1_000_000)

    def factory():
        client = default_client_factory()
        hooks = dict(client.event_hooks)
        hooks["response"] = [*hooks.get("response", []), hook]
        client.event_hooks = hooks
        return client

    set_client_factory(factory)
    return True
