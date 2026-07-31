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
