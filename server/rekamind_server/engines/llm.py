"""Summary + task extraction through any OpenAI-compatible chat endpoint
(Groq, OpenAI, Ollama, vLLM, LM Studio)."""

import json
import logging
import time

import httpx
from pydantic import ValidationError

from ..schemas import ExtractionResult
from .base import ExtractionInput

log = logging.getLogger(__name__)

CHUNK_CHARS = 12_000  # ~3k tokens + prompt + answer: stays under small per-minute token caps (Groq free: 8000)
MIN_CHUNK_CHARS = 1_500  # below this a request that is still 'too large' is a real failure, not a size problem
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
- "key_points": 3 sampai 7 hal PALING penting yang perlu diingat atau dicatat oleh orang yang tidak hadir (topik utama, fakta, angka, kondisi, risiko, kesimpulan), masing-masing satu kalimat padat. Ini intisari, BUKAN rincian per waktu: jangan mengulang isi "minutes" satu per satu. Kosongkan jika rapat memang tidak memuat hal penting.
- "decisions": hal yang disepakati, disimpulkan, dipilih, disetujui, atau arah yang ditetapkan, walaupun tidak diucapkan dengan kata "putuskan" atau "sepakat" (mis. "oke kita pakai vendor A", "berarti peluncuran digeser ke Senin", "setuju"). Satu kalimat yang menyebut apa yang diputuskan. Usulan, pertanyaan, atau pendapat yang belum disetujui BUKAN keputusan. Kosongkan jika memang tidak ada.
- "minutes": rincian jalannya rapat berurutan waktu, lebih detail daripada "key_points", dengan "time" disalin dari penanda waktu transkrip.
Balas HANYA JSON valid sesuai skema; tanpa teks lain."""

_SCHEMA_HINT = """\
Skema JSON:
{"overview": str, "key_points": [str], "decisions": [str],
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


class LlmTooLarge(LlmError):
    """The request exceeds the provider's size or per-minute token limit: sending less can succeed."""


_TOO_LARGE_HINTS = ("request too large", "context length", "maximum context", "reduce the length", "too many tokens")


class OpenAiCompatExtractor:
    def __init__(self, base_url: str, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, chunk_chars: int = CHUNK_CHARS):
        self._model = model
        self._chunk_chars = max(chunk_chars, MIN_CHUNK_CHARS)
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
            text = r.text[:600].lower()
            # A request bigger than the limit never succeeds by waiting; the caller splits it. (A 429 that
            # only says "tokens per minute ... try again in 5s" is a rate limit and is retried below.)
            if r.status_code == 413 or (r.status_code in (400, 429) and any(h in text for h in _TOO_LARGE_HINTS)):
                raise LlmTooLarge(f"LLM menolak ukuran permintaan ({r.status_code}): {r.text[:200]}")
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
                result = ExtractionResult.model_validate(json.loads(_strip_fences(raw)))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = str(exc)[:300]
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"JSON tidak valid ({last_err}). Balas ulang HANYA JSON yang benar."}]
                continue
            if result.overview.strip() or result.key_points or result.decisions or result.minutes or result.tasks:
                return result
            # Every field has a default, so "{}" validates. A meeting with words in it never has nothing to summarise:
            # it is a bad answer, not an empty one (it used to be saved as a blank summary and shown as "done").
            log.warning("LLM returned an empty extraction; raw reply: %r", raw[:300])
            last_err = "semua kolom kosong"
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "Jawabanmu kosong. Isi overview, key_points, decisions, minutes, dan tasks "
                                                     "berdasarkan transkrip. Balas ulang HANYA JSON yang benar."}]
        raise LlmError(f"LLM mengembalikan format yang tidak valid: {last_err}")

    def _extract_fitting(self, inp: ExtractionInput, text: str, part: int, total: int) -> list[ExtractionResult]:
        """One chunk, or - when the provider says it is too big - its two halves, recursively."""
        try:
            return [self._extract_chunk(inp, text, part, total)]
        except LlmTooLarge:
            if len(text) <= MIN_CHUNK_CHARS:
                raise
            log.info("LLM request too large (%d chars): splitting", len(text))
            halves = chunk_transcript(text, max(len(text) // 2 + 200, MIN_CHUNK_CHARS // 2))
            if len(halves) < 2:
                raise
            return [r for h in halves for r in self._extract_fitting(inp, h, part, total + 1)]

    # -- public --------------------------------------------------------------
    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        chunks = chunk_transcript(inp.transcript, self._chunk_chars)
        parts = [r for i, c in enumerate(chunks) for r in self._extract_fitting(inp, c, i + 1, len(chunks))]
        if len(parts) == 1:
            return parts[0]
        # Merge: tasks/decisions/minutes concatenate (the pipeline de-duplicates tasks);
        # the overview is rebuilt from the per-part overviews so it covers the whole meeting.
        merged = ExtractionResult(
            key_points=list(dict.fromkeys(k for p in parts for k in p.key_points)),
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
