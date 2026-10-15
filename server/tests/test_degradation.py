"""A missing or failing optional stage must not throw away the expensive one (the transcript)."""
from wavs import WAV

from rekamind_server.engines.fake import FakeExtractor
from rekamind_server.engines.llm import LlmError
from rekamind_server.worker import Worker


class BrokenDiarizer:
    def diarize(self, wav, num_speakers=None):
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


async def test_a_recording_without_speech_does_not_call_the_llm(client):
    class Silent:
        def transcribe(self, wav, language):
            return []

    class MustNotRun:
        def extract(self, inp):
            raise AssertionError("an LLM call was made for an empty transcript")

    client.app.state.engines.transcriber = Silent()
    client.app.state.engines.extractor = MustNotRun()
    m = await _upload(client)
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    # nothing to review (no tasks can exist), so it is finished; the warning still says why it is empty
    assert d["status"] == "done" and d["segments"] == [] and d["summary"] is None
    assert "Tidak ada ucapan terdeteksi" in d["error"]


class RecordingDiarizer:
    """Remembers the speaker-count hint it was given."""

    def __init__(self):
        self.seen = []

    def diarize(self, wav, num_speakers=None):
        self.seen.append(num_speakers)
        return []


async def test_the_users_speaker_count_reaches_the_diarizer_and_survives_reprocessing(client):
    rec = RecordingDiarizer()
    client.app.state.engines.diarizer = rec
    m = await _upload(client)

    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    assert rec.seen == [None], "nothing was set: let pyannote detect"

    r = await client.patch(f"/api/meetings/{m}", json={"num_speakers": 3})
    assert r.status_code == 200 and r.json()["num_speakers"] == 3
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    assert rec.seen == [None, 3]
    assert (await client.get(f"/api/meetings/{m}")).json()["num_speakers"] == 3


async def test_num_speakers_is_validated_and_clearable_and_renaming_leaves_it_alone(client):
    m = await _upload(client)
    for bad in ({"num_speakers": 0}, {"num_speakers": 99}, {"num_speakers": "tiga"}, {}, {"title": None}):
        assert (await client.patch(f"/api/meetings/{m}", json=bad)).status_code == 422, bad
    assert (await client.patch(f"/api/meetings/{m}", json={"num_speakers": 4})).json()["num_speakers"] == 4
    r = await client.patch(f"/api/meetings/{m}", json={"title": "Baru"})
    assert r.json()["title"] == "Baru" and r.json()["num_speakers"] == 4, "a rename must not clear the hint"
    r = await client.patch(f"/api/meetings/{m}", json={"num_speakers": None})
    assert r.status_code == 200 and r.json()["num_speakers"] is None and r.json()["title"] == "Baru"


class NoTaskExtractor:
    def extract(self, inp):
        r = FakeExtractor().extract(inp)
        r.tasks = []
        return r


async def test_a_meeting_with_nothing_to_review_is_done_not_stuck_in_review(client):
    client.app.state.engines.extractor = NoTaskExtractor()
    m = await _upload(client)
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    assert d["status"] == "done" and d["tasks"] == [] and d["summary"] is not None


async def test_a_failed_summary_still_needs_attention_and_keeps_its_retry(client):
    flaky = FlakyExtractor()
    client.app.state.engines.extractor = flaky
    m = await _upload(client)
    await client.post(f"/api/meetings/{m}/process")
    await _run(client)
    d = (await client.get(f"/api/meetings/{m}")).json()
    assert d["status"] == "review" and d["summary"] is None and "Ringkasan dan task belum dibuat" in d["error"]
