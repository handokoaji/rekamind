"""The download guard: a model download that crawls is cut off so it retries on a fresh connection (see hfguard.py)."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("huggingface_hub")
from rekamind_server import hfguard  # noqa: E402

httpx = hfguard._httpx()
CHUNK = 65536


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Inner:
    """A byte stream whose speed is a function of the (fake) time, so the tests need no sleeping."""

    def __init__(self, clock, rate_at, until):
        self.clock, self.rate_at, self.until, self.closed = clock, rate_at, until, False

    def __iter__(self):
        while self.clock.t < self.until:
            self.clock.t += CHUNK / self.rate_at(self.clock.t)
            yield b"x" * CHUNK

    def close(self):
        self.closed = True


def run(rate_at, until, min_bps=500_000):
    clock = Clock()
    inner = Inner(clock, rate_at, until)
    n = sum(len(c) for c in hfguard.GuardedStream(inner, min_bps, clock))
    return clock.t, n


def test_a_crawling_download_is_cut_off_after_the_grace_period():
    clock = Clock()
    inner = Inner(clock, lambda t: 100_000, until=300)  # the 0.1 MB/s node seen in production
    with pytest.raises(httpx.ReadTimeout):
        list(hfguard.GuardedStream(inner, 500_000, clock))
    assert hfguard.GRACE <= clock.t < hfguard.GRACE + 3, "cut off soon after the grace period, not after minutes"
    assert inner.closed, "the slow connection is closed so the retry gets a new one"


def test_a_healthy_download_is_left_alone():
    t, n = run(lambda t: 27_000_000, until=60)
    assert t >= 60 and n > 100_000_000


def test_a_slow_start_that_recovers_is_not_cut_off():
    t, n = run(lambda t: 50_000 if t < 5 else 20_000_000, until=40)
    assert t >= 40


def test_a_short_slow_download_finishes_inside_the_grace_period():
    t, n = run(lambda t: 100_000, until=hfguard.GRACE - 2)
    assert n > 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        total, pause = 2_000_000, (0.05 if self.path == "/slow" else 0)
        self.send_response(200)
        self.send_header("content-length", str(total))
        self.end_headers()
        try:
            sent = 0
            while sent < total:
                self.wfile.write(b"x" * 20_000)
                sent += 20_000
                time.sleep(pause)
        except OSError:  # the client hung up on purpose
            pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_installed_in_the_huggingface_client_it_cuts_slow_responses_only(server, monkeypatch):
    from huggingface_hub import set_client_factory
    from huggingface_hub.utils import _http

    monkeypatch.setattr(hfguard, "MIN_GUARDED_BYTES", 100_000)
    monkeypatch.setattr(hfguard, "GRACE", 0.4)
    monkeypatch.setattr(hfguard, "WINDOW", 0.5)
    assert hfguard.install(min_mbps=1.0)
    try:
        client = _http.get_session()
        with client.stream("GET", server + "/slow") as r, pytest.raises(httpx.ReadTimeout):  # 0.4 MB/s < 1 MB/s
            for _ in r.iter_bytes():
                pass
        with client.stream("GET", server + "/fast") as r:
            assert sum(len(c) for c in r.iter_bytes()) == 2_000_000
    finally:
        set_client_factory(_http.default_client_factory)


def test_it_can_be_switched_off():
    assert hfguard.install(min_mbps=0) is False
