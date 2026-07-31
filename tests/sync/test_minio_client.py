from datetime import datetime, timezone

from app.storage.models import Speaker, Summary, TranscriptSegment, Meeting
from app.sync import minio_client


def test_build_manifest_includes_meeting_fields_and_final_segments_only():
    meeting = Meeting(
        id=1, title="Rapat Rilis", device_id="dev1", device_label="Laptop Budi",
        status="completed",
        start_time=datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc),
    )
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=None, source="mic",
                           start_ms=0, end_ms=900, text="Halo", is_final=True),
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=900, end_ms=1500, text="Draft", is_final=False),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["title"] == "Rapat Rilis"
    assert manifest["device_id"] == "dev1"
    assert manifest["device_label"] == "Laptop Budi"
    assert manifest["status"] == "completed"
    assert manifest["start_time"] == "2026-07-31T09:00:00+00:00"
    assert len(manifest["segments"]) == 1  # the draft (is_final=False) is excluded
    assert manifest["segments"][0] == {
        "speaker_label": "Anda", "source": "mic", "start_ms": 0, "end_ms": 900, "text": "Halo",
    }
    assert manifest["summary"] is None


def test_build_manifest_resolves_speaker_labels_for_non_mic_segments():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="recorded")
    speakers_by_id = {5: Speaker(id=5, meeting_id=1, label="Speaker 1")}
    segments = [
        TranscriptSegment(meeting_id=1, speaker_id=5, source="speaker",
                           start_ms=0, end_ms=500, text="Mari mulai", is_final=True),
    ]

    manifest = minio_client.build_manifest(meeting, segments, speakers_by_id, summary=None)

    assert manifest["segments"][0]["speaker_label"] == "Speaker 1"


def test_build_manifest_includes_summary_when_present():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(
        meeting_id=1, mom_json='{"x": 1}', docx_path="/some/path/mom.docx",
        groq_model="openai/gpt-oss-120b", status="ready",
    )

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"] == {
        "mom_json": '{"x": 1}', "has_docx": True,
        "groq_model": "openai/gpt-oss-120b", "status": "ready",
    }


def test_build_manifest_summary_has_docx_false_when_docx_path_is_none():
    meeting = Meeting(id=1, title="Rapat", device_id="dev1", status="completed")
    summary = Summary(meeting_id=1, mom_json="{}", docx_path=None, groq_model="m", status="ready")

    manifest = minio_client.build_manifest(meeting, [], {}, summary=summary)

    assert manifest["summary"]["has_docx"] is False


def test_manifest_object_prefix_shape():
    assert minio_client.manifest_object_prefix("dev1", "uuid123") == "dev1/uuid123"
