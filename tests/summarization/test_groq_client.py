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


def test_summarize_chunks_long_transcript_and_reduces(monkeypatch):
    monkeypatch.setattr("app.summarization.groq_client._CHUNK_CHAR_BUDGET", 50)

    part_mom = {
        "minute_by_minute": [{"time": "00:00", "point": "bagian"}],
        "decisions": [],
        "action_items": [],
        "detailed_notes": "bagian",
    }
    final_mom = {
        "minute_by_minute": [{"time": "00:00", "point": "Pembukaan rapat"}],
        "decisions": ["Rilis ditunda ke minggu depan"],
        "action_items": [{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        "detailed_notes": "Rapat membahas kesiapan rilis.",
    }

    def fake_create(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        payload = final_mom if "menggabungkan" in prompt else part_mom
        return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))])

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = fake_create

    monkeypatch.setattr(
        "app.summarization.groq_client.Groq",
        lambda api_key: fake_client,
    )

    summarizer = GroqSummarizer(api_key="fake-key")
    long_transcript = "\n".join(f"Speaker {i}: kalimat panjang nomor {i}" for i in range(10))
    result = summarizer.summarize("Rapat Rilis", long_transcript)

    assert result == MomResult(
        minute_by_minute=[{"time": "00:00", "point": "Pembukaan rapat"}],
        decisions=["Rilis ditunda ke minggu depan"],
        action_items=[{"item": "Update changelog", "assignee": "Budi", "due": "2026-08-01"}],
        detailed_notes="Rapat membahas kesiapan rilis.",
    )
    assert fake_client.chat.completions.create.call_count > 2
