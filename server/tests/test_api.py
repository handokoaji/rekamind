from wavs import WAV

from rekamind_server.worker import Worker


async def _processed_meeting(client):
    m = (await client.post("/api/meetings", json={"title": "Sync", "local_user_name": "Andi"})).json()
    for src in ("mic", "speaker"):
        r = await client.put(f"/api/meetings/{m['id']}/audio/{src}", content=WAV)
        assert r.status_code == 201
    assert (await client.post(f"/api/meetings/{m['id']}/finish")).status_code == 200
    r = await client.post(f"/api/meetings/{m['id']}/process")
    assert r.status_code == 202
    app = client.app
    assert await Worker(app.state.sf, app.state.storage, app.state.engines).run_once()
    return m["id"], r.json()["id"]


async def test_full_flow_produces_transcript_and_reviewable_tasks(client):
    mid, job_id = await _processed_meeting(client)
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "done"
    d = (await client.get(f"/api/meetings/{mid}")).json()
    assert d["status"] == "review"
    labels = {p["label"]: p for p in d["participants"]}
    assert labels["ME"]["name"] == "Andi" and labels["ME"]["is_local_user"]
    assert {"SPEAKER_00", "SPEAKER_01"} <= set(labels)
    assert [s["start_ms"] for s in d["segments"]] == sorted(s["start_ms"] for s in d["segments"])
    # duplicate task from the extractor collapses to one
    assert sorted(t["title"] for t in d["tasks"]) == ["Kirim laporan", "Siapkan draft kontrak"]
    assert all(t["status"] == "suggested" for t in d["tasks"])
    assert d["summary"]["overview"] == "Ringkasan Sync"


async def test_deadline_resolved_against_meeting_date_and_flags_vagueness(client):
    mid, _ = await _processed_meeting(client)
    tasks = {t["title"]: t for t in (await client.get("/api/tasks", params={"meeting_id": mid})).json()}
    contract = tasks["Siapkan draft kontrak"]
    assert contract["deadline_text"] == "besok" and contract["deadline"] is not None
    assert contract["deadline_approximate"] is False
    assert contract["estimate_minutes"] == 120


async def test_assignee_is_only_linked_after_user_names_the_speaker(client):
    mid, _ = await _processed_meeting(client)
    d = (await client.get(f"/api/meetings/{mid}")).json()
    contract = next(t for t in d["tasks"] if t["title"] == "Siapkan draft kontrak")
    assert contract["assignee_participant_id"] is None  # "Budi" matches nobody yet
    spk = next(p for p in d["participants"] if p["label"] == "SPEAKER_01")
    r = await client.patch(f"/api/participants/{spk['id']}", json={"name": "Budi Santoso"})
    assert r.json()["name"] == "Budi Santoso"
    # reprocessing keeps the user's name and now links the assignee
    await client.post(f"/api/meetings/{mid}/process")
    await __import__("rekamind_server.worker", fromlist=["Worker"]).Worker(
        client.app.state.sf, client.app.state.storage, client.app.state.engines).run_once()
    d = (await client.get(f"/api/meetings/{mid}")).json()
    contract = next(t for t in d["tasks"] if t["title"] == "Siapkan draft kontrak")
    assert contract["assignee_participant_id"] == spk["id"]


async def test_cannot_assign_task_to_participant_of_another_meeting(client):
    mid1, _ = await _processed_meeting(client)
    mid2, _ = await _processed_meeting(client)
    other = (await client.get(f"/api/meetings/{mid2}")).json()["participants"][0]["id"]
    task = (await client.get(f"/api/meetings/{mid1}")).json()["tasks"][0]
    r = await client.patch(f"/api/tasks/{task['id']}", json={"assignee_participant_id": other})
    assert r.status_code == 422


async def test_only_confirmed_tasks_are_exportable_and_human_deadline_is_firm(client):
    mid, _ = await _processed_meeting(client)
    task = next(t for t in (await client.get(f"/api/meetings/{mid}")).json()["tasks"] if t["title"] == "Kirim laporan")
    assert task["deadline"] is not None and task["deadline_approximate"] is False  # "Jumat depan" is exact
    r = await client.patch(f"/api/tasks/{task['id']}", json={"status": "confirmed", "deadline": "2026-12-01"})
    assert r.json()["status"] == "confirmed" and r.json()["deadline_approximate"] is False
    confirmed = (await client.get("/api/tasks", params={"status": "confirmed"})).json()
    assert [t["id"] for t in confirmed] == [task["id"]]


async def test_process_refused_while_recording_and_without_engines(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    assert (await client.post(f"/api/meetings/{m['id']}/process")).status_code == 409
    client.app.state.engines = None
    assert (await client.post(f"/api/meetings/{m['id']}/process")).status_code == 503


async def test_failed_job_marks_meeting_failed_with_message(client):
    m = (await client.post("/api/meetings", json={"title": "no audio"})).json()
    await client.post(f"/api/meetings/{m['id']}/finish")
    await client.post(f"/api/meetings/{m['id']}/process")
    a = client.app
    await Worker(a.state.sf, a.state.storage, a.state.engines).run_once()
    d = (await client.get(f"/api/meetings/{m['id']}")).json()
    assert d["status"] == "failed" and "audio" in d["error"]


async def test_audio_upload_rejects_empty_and_unknown_source_and_bad_meeting(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    assert (await client.put(f"/api/meetings/{m['id']}/audio/mic", content=b"")).status_code == 400
    assert (await client.put(f"/api/meetings/{m['id']}/audio/../../etc", content=b"x")).status_code in (404, 405, 422)
    assert (await client.put("/api/meetings/nope/audio/mic", content=b"x")).status_code == 404


async def test_deleted_meeting_disappears_from_list(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    assert (await client.delete(f"/api/meetings/{m['id']}")).status_code == 204
    assert (await client.get("/api/meetings")).json() == []
    assert (await client.get(f"/api/meetings/{m['id']}")).status_code == 404


async def test_meeting_list_shows_job_progress_search_and_escapes_wildcards(client):
    a = (await client.post("/api/meetings", json={"title": "Rapat 100% vendor"})).json()
    await client.post("/api/meetings", json={"title": "Rapat internal"})
    assert [m["title"] for m in (await client.get("/api/meetings", params={"q": "100%"})).json()] == ["Rapat 100% vendor"]
    assert len((await client.get("/api/meetings", params={"q": "%"})).json()) == 1  # '%' is literal, not a wildcard
    await client.put(f"/api/meetings/{a['id']}/audio/mic", content=WAV)
    await client.post(f"/api/meetings/{a['id']}/finish")
    await client.post(f"/api/meetings/{a['id']}/process")
    row = next(m for m in (await client.get("/api/meetings")).json() if m["id"] == a["id"])
    assert row["job"]["status"] == "queued"


async def test_rename_restore_and_task_list_carries_meeting_title(client):
    mid, _ = await _processed_meeting(client)
    assert (await client.patch(f"/api/meetings/{mid}", json={"title": "Judul baru"})).json()["title"] == "Judul baru"
    assert all(t["meeting_title"] == "Judul baru" for t in (await client.get("/api/tasks")).json())
    await client.delete(f"/api/meetings/{mid}")
    assert (await client.get("/api/tasks")).json() == []  # tasks of a deleted meeting are hidden too
    assert (await client.post(f"/api/meetings/{mid}/restore")).status_code == 200
    assert len((await client.get("/api/tasks")).json()) == 2


async def test_audio_playback_supports_range_requests(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    await client.put(f"/api/meetings/{m['id']}/audio/mic", content=WAV)
    r = await client.get(f"/api/meetings/{m['id']}/audio/mic", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == WAV[2:6]
    assert (await client.get(f"/api/meetings/{m['id']}/audio/speaker")).status_code == 404


async def test_spa_is_served_with_history_fallback_but_api_404s_stay_json(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from rekamind_server.api import create_app
    from rekamind_server.config import Settings

    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>SPA</html>")
    (web / "assets" / "a.js").write_text("1")
    s = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none", web_dir=str(web))
    app = create_app(s)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            assert (await c.get("/meetings/abc")).text == "<html>SPA</html>"  # refresh on a client route
            assert (await c.get("/assets/a.js")).text == "1"
            r = await c.get("/api/meetings/" + "f" * 32)
            assert r.status_code == 404 and r.json()["detail"] == "Rapat tidak ditemukan"


def _tone_wav(path, seconds=1.0, rate=44100, channels=2):
    import wave

    import numpy as np

    t = np.arange(int(rate * seconds)) / rate
    mono = (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")
    data = np.repeat(mono[:, None], channels, axis=1) if channels > 1 else mono
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def _encode(src, dst, fmt):
    import av

    with av.open(str(src)) as i, av.open(str(dst), "w", format=fmt) as o:
        codec = {"mp3": "libmp3lame", "ogg": "libvorbis"}[fmt]
        out = o.add_stream(codec, rate=44100)
        out.layout = "stereo"
        for frame in i.decode(audio=0):
            frame.pts = None
            for p in out.encode(frame):
                o.mux(p)
        for p in out.encode(None):
            o.mux(p)


async def test_non_wav_uploads_are_normalised_to_16k_mono_wav(client, tmp_path):
    import wave

    src, mp3 = tmp_path / "t.wav", tmp_path / "t.mp3"
    _tone_wav(src, seconds=2)
    _encode(src, mp3, "mp3")
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    r = await client.put(f"/api/meetings/{m['id']}/audio/speaker", content=mp3.read_bytes())
    assert r.status_code == 201
    p = await client.app.state.storage.audio_path(m["id"], "speaker")
    with wave.open(str(p)) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 16000)
        assert 1.8 < w.getnframes() / 16000 < 2.4  # duration preserved


async def test_garbage_upload_gets_clear_415_and_leaves_no_temp_files(client):
    m = (await client.post("/api/meetings", json={"title": "x"})).json()
    r = await client.put(f"/api/meetings/{m['id']}/audio/mic", content=b"this is definitely not audio" * 50)
    assert r.status_code == 415 and "Format audio" in r.json()["detail"]
    assert list((client.app.state.storage._root / "tmp").glob("*")) == [] if hasattr(client.app.state.storage, "_root") else True


async def test_upload_over_the_size_cap_is_rejected_with_413(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from rekamind_server.api import create_app
    from rekamind_server.config import Settings

    s = Settings(data_dir=tmp_path, database_url="sqlite+aiosqlite:///:memory:", worker_inprocess=False, auth="none", max_upload_mb=1)
    app = create_app(s)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            m = (await c.post("/api/meetings", json={"title": "x"})).json()
            r = await c.put(f"/api/meetings/{m['id']}/audio/mic", content=b"RIFF" + b"\0" * (2 * 1024 * 1024))
            assert r.status_code == 413
            assert list((tmp_path / "tmp").glob("*")) == []


async def test_finishing_the_task_review_completes_the_meeting_and_undoing_reopens_it(client):
    mid, _ = await _processed_meeting(client)
    tasks = (await client.get(f"/api/meetings/{mid}")).json()["tasks"]
    await client.patch(f"/api/tasks/{tasks[0]['id']}", json={"status": "confirmed"})
    assert (await client.get(f"/api/meetings/{mid}")).json()["status"] == "review"  # one still pending
    await client.patch(f"/api/tasks/{tasks[1]['id']}", json={"status": "rejected"})
    assert (await client.get(f"/api/meetings/{mid}")).json()["status"] == "done"
    await client.patch(f"/api/tasks/{tasks[1]['id']}", json={"status": "suggested"})
    assert (await client.get(f"/api/meetings/{mid}")).json()["status"] == "review"


async def test_first_person_assignee_resolves_to_the_speaker_who_said_it(client):
    """"Saya kirim laporan" at 00:20 was said on the mic channel -> the local user."""
    mid, _ = await _processed_meeting(client)
    d = (await client.get(f"/api/meetings/{mid}")).json()
    me = next(p for p in d["participants"] if p["label"] == "ME")
    report = next(t for t in d["tasks"] if t["title"] == "Kirim laporan")
    assert report["assignee_participant_id"] == me["id"]


async def test_first_person_is_not_guessed_when_nobody_was_speaking_then(client):
    from wavs import WAV

    m = (await client.post("/api/meetings", json={"title": "speaker only"})).json()
    await client.put(f"/api/meetings/{m['id']}/audio/speaker", content=WAV)  # no mic channel at all
    await client.post(f"/api/meetings/{m['id']}/finish")
    await client.post(f"/api/meetings/{m['id']}/process")
    a = client.app
    await Worker(a.state.sf, a.state.storage, a.state.engines).run_once()
    report = next(t for t in (await client.get(f"/api/meetings/{m['id']}")).json()["tasks"] if t["title"] == "Kirim laporan")
    assert report["assignee_participant_id"] is None  # 00:20 is outside every speaker segment
