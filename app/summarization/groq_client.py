import json
import time
from dataclasses import dataclass

from groq import Groq

# ponytail: char-count proxy for token budget (~4 chars/token) to stay under
# Groq's on_demand TPM cap (8000) including prompt overhead + response. Bump
# down if a model/tier with a smaller cap is ever configured.
_CHUNK_CHAR_BUDGET = 12000
_TPM_LIMIT = 8000
_CHARS_PER_TOKEN = 4


def _pause_for_rate_limit() -> None:
    tokens_per_request = _CHUNK_CHAR_BUDGET / _CHARS_PER_TOKEN
    time.sleep(60 * tokens_per_request / _TPM_LIMIT)

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

_MAP_PROMPT_TEMPLATE = """\
Kamu adalah asisten yang membuat catatan rapat dalam Bahasa Indonesia dari \
SEBAGIAN transkrip rapat berikut (bagian {part} dari {total}). Judul rapat: "{title}".

Transkrip (sebagian):
{transcript}

Balas HANYA dengan JSON valid persis dengan struktur ini, tanpa teks lain:
{{
  "minute_by_minute": [{{"time": "mm:ss", "point": "..."}}],
  "decisions": ["..."],
  "action_items": [{{"item": "...", "assignee": "...", "due": "..."}}],
  "detailed_notes": "catatan detail dari bagian ini dalam Bahasa Indonesia"
}}
"""

_REDUCE_PROMPT_TEMPLATE = """\
Kamu adalah asisten yang menggabungkan beberapa catatan parsial rapat (JSON, \
urut sesuai waktu) menjadi satu Minutes of Meeting (MoM) final dalam Bahasa \
Indonesia. Judul rapat: "{title}".

Catatan parsial:
{parts_json}

Gabungkan menjadi satu MoM utuh: urutkan minute_by_minute secara kronologis, \
hilangkan duplikat, dan satukan detailed_notes jadi satu narasi. Balas HANYA \
dengan JSON valid persis dengan struktur ini, tanpa teks lain:
{{
  "minute_by_minute": [{{"time": "mm:ss", "point": "..."}}],
  "decisions": ["..."],
  "action_items": [{{"item": "...", "assignee": "...", "due": "..."}}],
  "detailed_notes": "catatan detail dan lengkap dalam Bahasa Indonesia"
}}
"""


def _chunk_transcript(transcript_text: str, budget: int | None = None) -> list[str]:
    budget = budget if budget is not None else _CHUNK_CHAR_BUDGET
    lines = transcript_text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > budget:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    chunks.append("\n".join(current))
    return chunks


def _to_mom(data: dict) -> "MomResult":
    return MomResult(
        minute_by_minute=data["minute_by_minute"],
        decisions=data["decisions"],
        action_items=data["action_items"],
        detailed_notes=data["detailed_notes"],
    )


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

    def _request(self, prompt: str) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    def summarize(self, meeting_title: str, transcript_text: str) -> MomResult:
        chunks = _chunk_transcript(transcript_text)
        if len(chunks) == 1:
            prompt = _PROMPT_TEMPLATE.format(title=meeting_title, transcript=chunks[0])
            return _to_mom(self._request(prompt))

        parts = []
        for i, chunk in enumerate(chunks):
            if i:
                _pause_for_rate_limit()
            parts.append(
                self._request(
                    _MAP_PROMPT_TEMPLATE.format(
                        title=meeting_title, part=i + 1, total=len(chunks), transcript=chunk
                    )
                )
            )
        _pause_for_rate_limit()
        reduce_prompt = _REDUCE_PROMPT_TEMPLATE.format(
            title=meeting_title, parts_json=json.dumps(parts, ensure_ascii=False)
        )
        return _to_mom(self._request(reduce_prompt))
