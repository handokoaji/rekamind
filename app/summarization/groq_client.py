import json
from dataclasses import dataclass

from groq import Groq

_PROMPT_TEMPLATE = """\
Kamu adalah asisten yang membuat Minutes of Meeting (MoM) dalam Bahasa \
Indonesia dari transkrip rapat berikut. Judul rapat: "{title}".

Transkrip:
{transcript}

Balas HANYA dengan JSON valid persis dengan struktur ini, tanpa teks lain:
{{
  "minute_by_minute": [{{"time": "mm:ss", "point": "..."}}],
  "decisions": ["..."],
  "action_items": [{{"item": "...", "assignee": "...", "due": "..."}}],
  "detailed_notes": "catatan detail dan lengkap dalam Bahasa Indonesia"
}}
"""


@dataclass
class MomResult:
    minute_by_minute: list[dict]
    decisions: list[str]
    action_items: list[dict]
    detailed_notes: str


class GroqSummarizer:
    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b"):
        self._client = Groq(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def summarize(self, meeting_title: str, transcript_text: str) -> MomResult:
        prompt = _PROMPT_TEMPLATE.format(title=meeting_title, transcript=transcript_text)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return MomResult(
            minute_by_minute=data["minute_by_minute"],
            decisions=data["decisions"],
            action_items=data["action_items"],
            detailed_notes=data["detailed_notes"],
        )
