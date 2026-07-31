import json
from unittest.mock import MagicMock

from app.summarization.groq_client import GroqSummarizer, MomResult


def test_summarize_parses_json_response(monkeypatch):
    fake_mom = {
        "minute_by_minute": [{"time": "00:00", "point": "Pembukaan rapat"}],
        "decisions": ["Rilis ditunda ke minggu depan"],
        "action_items": [{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        "detailed_notes": "Rapat membahas kesiapan rilis.",
    }
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=json.dumps(fake_mom)))]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    monkeypatch.setattr(
        "app.summarization.groq_client.Groq",
        lambda api_key: fake_client,
    )

    summarizer = GroqSummarizer(api_key="fake-key")
    result = summarizer.summarize("Rapat Rilis", "Anda: halo semua\nSpeaker 1: mari mulai")

    assert result == MomResult(
        minute_by_minute=[{"time": "00:00", "point": "Pembukaan rapat"}],
        decisions=["Rilis ditunda ke minggu depan"],
        action_items=[{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        detailed_notes="Rapat membahas kesiapan rilis.",
    )
    fake_client.chat.completions.create.assert_called_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-oss-120b"
    assert call_kwargs["response_format"] == {"type": "json_object"}


def test_summarize_chunks_long_transcript_and_merges_without_extra_llm_call(monkeypatch):
    monkeypatch.setattr("app.summarization.groq_client._CHUNK_CHAR_BUDGET", 50)
    sleep_calls = []
    monkeypatch.setattr("app.summarization.groq_client.time.sleep", sleep_calls.append)

    part_moms = [
        {
            "minute_by_minute": [{"time": f"0{i}:00", "point": f"bagian {i}"}],
            "decisions": ["Rilis ditunda ke minggu depan"] if i == 0 else [],
            "action_items": [{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}]
            if i == 0
            else [],
            "detailed_notes": f"catatan bagian {i}",
        }
        for i in range(4)
    ]

    def fake_create(**kwargs):
        payload = part_moms[fake_create.calls]
        fake_create.calls += 1
        return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))])

    fake_create.calls = 0

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = fake_create

    monkeypatch.setattr(
        "app.summarization.groq_client.Groq",
        lambda api_key: fake_client,
    )

    summarizer = GroqSummarizer(api_key="fake-key")
    long_transcript = "\n".join(
        f"Speaker {i}: kalimat panjang nomor {i}" for i in range(len(part_moms))
    )
    result = summarizer.summarize("Rapat Rilis", long_transcript)

    call_count = fake_client.chat.completions.create.call_count
    assert call_count == len(part_moms)  # one call per chunk, no extra reduce call
    assert len(sleep_calls) == call_count - 1  # paced between chunk calls only

    assert result.minute_by_minute == [
        {"time": "00:00", "point": "bagian 0"},
        {"time": "01:00", "point": "bagian 1"},
        {"time": "02:00", "point": "bagian 2"},
        {"time": "03:00", "point": "bagian 3"},
    ]
    assert result.decisions == ["Rilis ditunda ke minggu depan"]
    assert result.action_items == [
        {"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}
    ]
    assert result.detailed_notes == "catatan bagian 0\n\ncatatan bagian 1\n\ncatatan bagian 2\n\ncatatan bagian 3"
