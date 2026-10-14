"""Summary + task extraction through any OpenAI-compatible chat endpoint
(Groq, OpenAI, Ollama, vLLM, LM Studio)."""

import json
import logging
import time

import httpx
from pydantic import ValidationError

from ..schemas import ExtractedTask, ExtractionResult
from .base import ExtractionInput

log = logging.getLogger(__name__)

CHUNK_CHARS = 24_000  # ~6k tokens: fits small context windows and per-minute token caps
MAX_RETRIES = 4

_SYSTEM = """\
Kamu adalah asisten yang menyusun catatan rapat dalam Bahasa Indonesia dari transkrip.
Aturan ketat:
- Hanya masukkan TASK yang benar-benar disepakati atau ditugaskan dalam rapat. Jangan mengarang task, \
nama, tanggal, atau durasi. Jika tidak disebutkan, isi null.
- "assignee": nama persis seperti yang diucapkan (bukan label SPEAKER). Null jika tidak ada penanggung jawab.
- "deadline_text": salin frasa tenggat PERSIS seperti diucapkan (mis. "Jumat depan"). Jangan hitung tanggal sendiri.
- "estimate_minutes": hanya jika durasi pengerjaan disebut; ubah ke menit.
- "evidence_time": salin penanda waktu [mm:ss] dari baris transkrip tempat task itu dibicarakan (tanpa kurung siku), \
dan "evidence_quote": kutipan singkat dari transkrip.
- "confidence": 0..1, turunkan bila tugas/penanggung jawab/tenggat ambigu.
- "minutes": poin per waktu dengan "time" disalin dari penanda waktu transkrip.
Balas HANYA JSON valid sesuai skema; tanpa teks lain."""

_SCHEMA_HINT = """\
Skema JSON:
{"overview": str, "decisions": [str],
 "minutes": [{"time": "mm:ss", "point": str}],
 "tasks": [{"title": str, "description": str, "assignee": str|null, "deadline_text": str|null,
            "estimate_minutes": int|null, "priority": "low"|"medium"|"high",
            "evidence_time": "mm:ss"|null, "evidence_quote": str, "confidence": number}]}"""


def chunk_transcript(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split on line boundaries so a [mm:ss] utterance is never cut in half."""
    chunks, cur, size = [], [], 0
    for line in text.split("\n"):
        if cur and size + len(line) + 1 > limit:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    chunks.append("\n".join(cur))
    return chunks


class LlmError(RuntimeError):
    pass


class OpenAiCompatExtractor:
    def __init__(self, base_url: str, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        self._model = model
        self._sleep = sleep
        self._json_schema_ok = True  # flipped off if the endpoint rejects response_format=json_schema
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=120, transport=transport)

    # -- transport -----------------------------------------------------------
    def _chat(self, messages: list[dict]) -> str:
        for attempt in range(MAX_RETRIES + 1):
            body = {"model": self._model, "messages": messages, "temperature": 0.1}
            body["response_format"] = (
                {"type": "json_schema", "json_schema": {"name": "extraction", "schema": ExtractionResult.model_json_schema()}}
                if self._json_schema_ok else {"type": "json_object"}
            )
            try:
                r = self._http.post("/chat/completions", json=body)
            except httpx.TransportError as exc:
                if attempt == MAX_RETRIES:
                    raise LlmError(f"Tidak bisa menghubungi layanan LLM: {exc}") from exc
                self._sleep(2 ** attempt)
                continue
            if r.status_code == 400 and self._json_schema_ok:
                self._json_schema_ok = False  # endpoint lacks structured output; fall back to json_object
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                try:
                    wait = float(r.headers.get("retry-after", ""))
                except ValueError:
                    wait = 2 ** attempt
                self._sleep(min(wait, 60))
                continue
            if r.status_code == 401:
                raise LlmError("API key LLM ditolak (401). Periksa REKAMIND_LLM_API_KEY.")
            if r.status_code >= 400:
                raise LlmError(f"LLM mengembalikan {r.status_code}: {r.text[:200]}")
            return r.json()["choices"][0]["message"]["content"]
        raise LlmError("LLM tidak merespons setelah beberapa percobaan")

    # -- one validated call --------------------------------------------------
    def _extract_chunk(self, inp: ExtractionInput, text: str, part: int, total: int) -> ExtractionResult:
        user = (
            f'Judul rapat: "{inp.title}". Tanggal rapat: {inp.started_at.date().isoformat()}. '
            f'Peserta: {", ".join(inp.participants) or "-"}.'
            + (f" Ini bagian {part} dari {total} transkrip." if total > 1 else "")
            + f"\n\n{_SCHEMA_HINT}\n\nTranskrip:\n{text}"
        )
        messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
        last_err = ""
        for _ in range(2):  # one corrective retry when the model returns invalid JSON
            raw = self._chat(messages)
            try:
                return ExtractionResult.model_validate(json.loads(_strip_fences(raw)))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = str(exc)[:300]
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"JSON tidak valid ({last_err}). Balas ulang HANYA JSON yang benar."}]
        raise LlmError(f"LLM mengembalikan format yang tidak valid: {last_err}")

    # -- public --------------------------------------------------------------
    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        chunks = chunk_transcript(inp.transcript)
        parts = [self._extract_chunk(inp, c, i + 1, len(chunks)) for i, c in enumerate(chunks)]
        if len(parts) == 1:
            return parts[0]
        # Merge: tasks/decisions/minutes concatenate (the pipeline de-duplicates tasks);
        # the overview is rebuilt from the per-part overviews so it covers the whole meeting.
        merged = ExtractionResult(
            decisions=list(dict.fromkeys(d for p in parts for d in p.decisions)),
            minutes=[m for p in parts for m in p.minutes],
            tasks=[t for p in parts for t in p.tasks],
            overview="\n".join(p.overview for p in parts if p.overview),
        )
        return merged

    def close(self) -> None:
        self._http.close()


def _strip_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()
