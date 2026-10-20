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
    "key_points": ["Vendor A lebih murah dari vendor B"],
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


def test_key_points_are_kept_apart_from_decisions_and_the_timeline_and_merged_without_repeats():
    r = _llm(lambda req: _reply(json.dumps(GOOD))).extract(_inp())
    assert r.key_points == ["Vendor A lebih murah dari vendor B"] and r.decisions == ["Pakai vendor A"]
    text = "\n".join(f"[{i:02d}:00] ME: " + "kalimat " * 50 for i in range(60))
    merged = _llm(lambda req: _reply(json.dumps(GOOD))).extract(_inp(text))
    assert len(chunk_transcript(text)) >= 2 and merged.key_points == ["Vendor A lebih murah dari vendor B"], "the same point from every chunk appears once"


def test_the_prompt_defines_decisions_and_key_points_and_keeps_them_short_of_a_second_timeline():
    from rekamind_server.engines import llm

    p = llm._SYSTEM
    assert '"key_points"' in p and "BUKAN rincian per waktu" in p
    assert "walaupun tidak diucapkan" in p and "BUKAN keputusan" in p, "implicit agreements count, bare proposals do not"
    assert '"key_points"' in llm._SCHEMA_HINT


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


def _long_transcript(lines=400):
    return "\n".join(f"[{i // 60:02d}:{i % 60:02d}] Budi: " + "kalimat rapat yang cukup panjang " * 6 for i in range(lines))


def test_a_413_too_large_request_is_split_until_it_fits_and_nothing_is_lost():
    # Found with a real 52-minute meeting on a free Groq key (8000 tokens/minute): 413 "Request too large"
    # used to fail the whole meeting. The provider here refuses anything over 6000 characters.
    sizes = []

    def handler(req):
        user = json.loads(req.content)["messages"][1]["content"]
        sizes.append(len(user))
        if len(user) > 6000:
            return httpx.Response(413, json={"error": {"message": "Request too large ... on tokens per minute (TPM): Limit 8000, Requested 10207"}})
        return _reply(json.dumps({**GOOD, "tasks": [{**GOOD["tasks"][0], "title": f"Tugas {len(sizes)}"}]}))

    r = _llm(handler).extract(_inp(_long_transcript()))
    assert max(sizes[-3:]) <= 6000 and len(r.tasks) >= 4, "split into several accepted requests"
    assert len({t.title for t in r.tasks}) == len(r.tasks), "every part contributed its own result"


def test_a_429_rate_limit_with_retry_after_is_waited_out_not_split():
    waits, calls = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "Rate limit reached on tokens per minute (TPM): Limit 8000, Used 7000, Requested 2000. Please try again in 3s"}})
        return _reply(json.dumps(GOOD))

    llm = OpenAiCompatExtractor("http://llm/v1", "k", "m", transport=httpx.MockTransport(handler), sleep=waits.append)
    assert llm.extract(_inp()).tasks and waits == [3.0] and len(calls) == 2


def test_a_request_that_is_too_large_even_when_tiny_fails_clearly():
    from rekamind_server.engines.llm import LlmTooLarge

    llm = _llm(lambda req: httpx.Response(413, json={"error": {"message": "Request too large"}}))
    with pytest.raises(LlmTooLarge):
        llm.extract(_inp(_long_transcript(60)))


def test_an_empty_json_answer_is_retried_not_saved_as_a_blank_summary():
    answers = iter(["{}", json.dumps(GOOD)])
    seen = []

    def handler(req):
        seen.append(json.loads(req.content)["messages"][-1]["content"])
        return _reply(next(answers))

    r = _llm(handler).extract(_inp())
    assert r.overview == "Rapat vendor" and len(seen) == 2 and "kosong" in seen[1]


def test_an_answer_that_stays_empty_is_an_error_the_user_can_retry():
    with pytest.raises(LlmError, match="tidak valid"):
        _llm(lambda req: _reply('{"overview": "  ", "decisions": [], "minutes": [], "tasks": []}')).extract(_inp())


# ---- topics: followed across the whole meeting ---------------------------------------------------------------------

def _topic(title, status="open", times=("01:00",), follow_up=None, summary="x"):
    return {"title": title, "summary": summary, "status": status, "times": list(times), "follow_up": follow_up}


def _is_merge(req):
    return json.loads(req.content)["messages"][0]["content"].startswith("Kamu merapikan")


def _long():
    return "\n".join(f"[{i:02d}:00] ME: " + "kalimat " * 50 for i in range(60))


def test_topics_keep_their_status_times_and_follow_up():
    reply = dict(GOOD, topics=[_topic("Kontrak vendor", "open", ["12:00", "40:10"], "Tentukan penanggung jawab")])
    r = _llm(lambda req: _reply(json.dumps(reply))).extract(_inp())
    t = r.topics[0]
    assert (t.title, t.status, t.times, t.follow_up) == ("Kontrak vendor", "open", ["12:00", "40:10"], "Tentukan penanggung jawab")


def test_a_topic_touched_thirty_times_lists_a_few_times_not_thirty():
    many = [f"{i:02d}:00" for i in range(30)]
    reply = dict(GOOD, topics=[_topic("Persiapan presentasi", times=many)])
    t = _llm(lambda req: _reply(json.dumps(reply))).extract(_inp()).topics[0]
    assert t.times == many[:5] + [many[-1]], "the first ones and the last"


def test_parts_are_joined_by_one_small_call_that_picks_by_number_and_decides_the_final_status():
    calls = {"parts": 0, "merge": 0}
    seen = {}

    def handler(req):
        if _is_merge(req):
            calls["merge"] += 1
            seen["prompt"] = json.loads(req.content)["messages"][1]["content"]
            # keep the second key point; every topic is the same subject ("Kontrak vendor"), settled in the end
            return _reply(json.dumps({"key_points": [2], "decisions": [1],
                                      "topics": [{"members": list(range(1, calls["parts"] + 1)), "status": "decided", "follow_up": None}]}))
        calls["parts"] += 1
        first = calls["parts"] == 1  # raised early, settled later
        return _reply(json.dumps(dict(GOOD, key_points=["poin a", "poin b"] if first else ["poin c"],
                                      topics=[_topic("Kontrak vendor", "open" if first else "decided", ["01:00"] if first else ["40:10"])])))

    r = _llm(handler).extract(_inp(_long()))
    assert calls["parts"] >= 2 and calls["merge"] == 1
    assert "KEY_POINTS:\n1. poin a\n2. poin b\n3. poin c" in seen["prompt"], "numbered, so the answer can be numbers"
    assert r.key_points == ["poin b"] and r.decisions == ["Pakai vendor A"]
    assert len(r.topics) == 1
    assert (r.topics[0].status, r.topics[0].times) == ("decided", ["01:00", "40:10"])


def test_when_the_join_fails_the_parts_are_kept_not_lost():
    def handler(req):
        if _is_merge(req):
            return _reply("bukan json")
        return _reply(json.dumps(dict(GOOD, topics=[_topic("Kontrak vendor")])))

    r = _llm(handler).extract(_inp(_long()))
    assert [t.title for t in r.topics] == ["Kontrak vendor"], "the same subject from every part, once"
    assert r.key_points == ["Vendor A lebih murah dari vendor B"] and r.decisions == ["Pakai vendor A"]


def test_what_the_model_does_not_mention_or_gets_wrong_is_kept_not_dropped():
    calls = {"parts": 0}

    def handler(req):
        if _is_merge(req):
            # one valid group, nonsense numbers for the key points, a non-list for the decisions
            return _reply(json.dumps({"key_points": [99, "x"], "decisions": 7,
                                      "topics": [{"members": [1, 1, 99], "status": "open", "follow_up": "Cek lagi"}]}))
        calls["parts"] += 1
        n = calls["parts"]
        return _reply(json.dumps(dict(GOOD, key_points=[f"poin {n}"], decisions=[f"keputusan {n}"], topics=[_topic(f"Topik {n}")])))

    r = _llm(handler).extract(_inp(_long()))
    assert len(r.topics) == calls["parts"], "no topic is lost"
    assert [t.follow_up for t in r.topics if t.title == "Topik 1"] == ["Cek lagi"], "the group the model did give is applied"
    assert len(r.key_points) == calls["parts"] and len(r.decisions) == calls["parts"], "unusable choices keep everything"


def test_a_transcript_that_fits_in_one_call_is_not_joined():
    seen = []

    def handler(req):
        seen.append(_is_merge(req))
        return _reply(json.dumps(dict(GOOD, topics=[_topic("Kontrak vendor")])))

    _llm(handler).extract(_inp())
    assert seen == [False]


def test_a_null_follow_up_from_the_join_does_not_erase_what_an_open_topic_still_needs():
    def handler(req):
        if _is_merge(req):
            return _reply(json.dumps({"topics": [
                # every part returns both topics, so they are numbered 1,2 / 3,4 / 5,6: odd = "Terbuka", even = "Selesai"
                {"members": [1, 3, 5, 7, 9], "status": "open", "follow_up": None},       # still open: keep the part's follow-up
                {"members": [2, 4, 6, 8, 10], "status": "decided", "follow_up": None},   # settled: nothing left to do
            ]}))
        return _reply(json.dumps(dict(GOOD, topics=[_topic("Terbuka", "open", follow_up="Cek vendor"), _topic("Selesai", "decided", follow_up="sisa lama")])))

    r = _llm(handler).extract(_inp(_long()))
    by_title = {t.title: t for t in r.topics}
    assert by_title["Terbuka"].follow_up == "Cek vendor"
    assert by_title["Selesai"].follow_up is None

