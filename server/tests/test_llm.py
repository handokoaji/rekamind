import json
from datetime import UTC, datetime

import httpx
import pytest

from rekamind_server.engines.base import ExtractionInput
from rekamind_server.engines.llm import (
    LlmError,
    OpenAiCompatExtractor,
    chunk_transcript,
)

GOOD = {
    "overview": "Rapat vendor",
    "decisions": ["Pakai vendor A"],
    "minutes": [{"time": "01:05", "point": "Bahas vendor"}],
    "tasks": [{"title": "Kirim penawaran", "assignee": "Budi", "deadline_text": "Jumat depan",
               "evidence_time": "01:05", "evidence_quote": "Budi kirim penawaran Jumat depan", "confidence": 0.8}],
}


def _inp(transcript="[00:01] ME: halo"):
    return ExtractionInput("Rapat", datetime(2026, 10, 14, tzinfo=UTC), "id", ["Budi"], transcript)


def _llm(handler):
    return OpenAiCompatExtractor("http://llm/v1", "k", "m", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def _reply(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_extracts_and_converts_clock_to_ms():
    r = _llm(lambda req: _reply(json.dumps(GOOD))).extract(_inp())
    assert r.tasks[0].evidence_start_ms == 65_000 and r.minutes[0].start_ms == 65_000
    assert r.tasks[0].deadline_text == "Jumat depan"


def test_accepts_markdown_fenced_json():
    r = _llm(lambda req: _reply("```json\n" + json.dumps(GOOD) + "\n```")).extract(_inp())
    assert r.overview == "Rapat vendor"


def test_falls_back_to_json_object_when_endpoint_rejects_json_schema():
    seen = []

    def h(req):
        fmt = json.loads(req.content)["response_format"]["type"]
        seen.append(fmt)
        return httpx.Response(400, text="unsupported") if fmt == "json_schema" else _reply(json.dumps(GOOD))

    assert _llm(h).extract(_inp()).overview == "Rapat vendor"
    assert seen == ["json_schema", "json_object"]


def test_corrective_retry_on_invalid_json_then_gives_up():
    calls = []

    def h(req):
        calls.append(1)
        return _reply("bukan json")

    with pytest.raises(LlmError, match="tidak valid"):
        _llm(h).extract(_inp())
    assert len(calls) == 2  # original + one corrective retry, not an endless loop


def test_schema_violation_is_rejected_not_silently_accepted():
    bad = dict(GOOD, tasks=[{"title": "x"}])  # title shorter than 3 chars
    with pytest.raises(LlmError):
        _llm(lambda req: _reply(json.dumps(bad))).extract(_inp())


def test_retries_429_honouring_retry_after_then_succeeds():
    waits, n = [], {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"retry-after": "7"}) if n["i"] == 1 else _reply(json.dumps(GOOD))

    llm = OpenAiCompatExtractor("http://llm/v1", "k", "m", transport=httpx.MockTransport(h), sleep=waits.append)
    assert llm.extract(_inp()).overview == "Rapat vendor"
    assert waits == [7.0]


def test_bad_key_gives_actionable_error():
    with pytest.raises(LlmError, match="401"):
        _llm(lambda req: httpx.Response(401)).extract(_inp())


def test_long_transcript_is_chunked_on_line_boundaries_and_merged():
    lines = [f"[{i:02d}:00] ME: " + "kalimat " * 50 for i in range(60)]
    text = "\n".join(lines)
    chunks = chunk_transcript(text, limit=5000)
    assert len(chunks) > 1 and "\n".join(chunks) == text
    assert all(c.split("\n")[0].startswith("[") for c in chunks)  # never cut mid-utterance
    r = _llm(lambda req: _reply(json.dumps(GOOD))).extract(_inp(text))
    assert len(r.tasks) == len(chunk_transcript(text))  # one call per default-size chunk; dedupe is the pipeline's job
    assert len(chunk_transcript(text)) >= 2
