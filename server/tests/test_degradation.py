"""A missing or failing optional stage must not throw away the expensive one (the transcript)."""
from wavs import WAV

from rekamind_server.engines.fake import FakeExtractor
from rekamind_server.engines.llm import LlmError
from rekamind_server.worker import Worker


class BrokenDiarizer:
    def diarize(self, wav):
        raise ModuleNotFoundError("No module named 'pickletools'")


class FlakyExtractor:
    """Fails (as Groq did with 413) until `works` is set."""

    works = False

    def extract(self, inp):
        if not self.works:
            raise LlmError("LLM mengembalikan 413: Request too large")
        return FakeExtractor().extract(inp)


async def _upload(client, title="Rapat"):
    m = (await client.post("/api/meetings", json={"title": title})).json()["id"]
    for src in ("mic", "speaker"):
        assert (await client.put(f"/api/meetings/{m}/audio/{src}", content=WAV)).status_code == 201
    await client.post(f"/api/meetings/{m}/finish")
    return m


async def _run(client):
    app = client.app
    assert await Worker(app.state.sf, app.state.storage, app.state.engines).run_once()


async def test_a_failing_diarizer_keeps_the_transcript_and_says_so(client):
    client.app.state.engines.diarizer = BrokenDiarizer()
    m = await _upload(client)
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    assert d["status"] == "review", d["error"]
    assert len(d["segments"]) == 4 and d["summary"] is not None and d["tasks"]
    assert "Pemisah pembicara gagal" in d["error"] and "pickletools" in d["error"]
    labels = {p["label"] for p in d["participants"]}
    assert labels == {"ME", "SPEAKER_00"}, "the computer's audio is one speaker, not UNKNOWN"


async def test_a_failing_llm_keeps_the_transcript_and_the_summary_can_be_retried_cheaply(client):
    flaky = FlakyExtractor()
    client.app.state.engines.extractor = flaky
    transcribed = []
    real = client.app.state.engines.transcriber.transcribe
    client.app.state.engines.transcriber.transcribe = lambda wav, lang: (transcribed.append(wav), real(wav, lang))[1]

    m = await _upload(client)
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    assert d["status"] == "review" and len(d["segments"]) == 4
    assert d["summary"] is None and d["tasks"] == []
    assert "Ringkasan dan task belum dibuat" in d["error"] and "413" in d["error"]
    assert len(transcribed) == 2

    flaky.works = True
    r = await client.post(f"/api/meetings/{m}/process", params={"stage": "extract"})
    assert r.status_code == 202
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    assert d["status"] == "review" and d["error"] is None
    assert d["summary"]["overview"] == "Ringkasan Rapat" and len(d["tasks"]) == 2
    assert len(transcribed) == 2, "the retry must not transcribe again"
    assert len(d["segments"]) == 4


async def test_retrying_only_the_summary_needs_a_transcript_and_does_not_run_beside_another_job(client):
    m = await _upload(client)
    r = await client.post(f"/api/meetings/{m}/process", params={"stage": "extract"})
    assert r.status_code == 409
    first = (await client.post(f"/api/meetings/{m}/process")).json()
    again = await client.post(f"/api/meetings/{m}/process")
    assert again.json()["id"] == first["id"]
