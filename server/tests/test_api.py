from rekamind_server.worker import Worker


async def _processed_meeting(client):
    m = (await client.post("/api/meetings", json={"title": "Sync", "local_user_name": "Andi"})).json()
    for src in ("mic", "speaker"):
        r = await client.put(f"/api/meetings/{m['id']}/audio/{src}", content=b"RIFFfake")
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
