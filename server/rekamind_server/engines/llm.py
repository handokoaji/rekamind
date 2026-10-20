"""Summary + task extraction through any OpenAI-compatible chat endpoint
(Groq, OpenAI, Ollama, vLLM, LM Studio)."""

import json
import logging
import time

import httpx
from pydantic import ValidationError

from ..schemas import ExtractionResult, Topic, parse_clock
from .base import ExtractionInput

log = logging.getLogger(__name__)

CHUNK_CHARS = 12_000  # ~3k tokens + prompt + answer: stays under small per-minute token caps (Groq free: 8000)
MIN_CHUNK_CHARS = 1_500  # below this a request that is still 'too large' is a real failure, not a size problem
MAX_RETRIES = 4

_SYSTEM = """\
Kamu adalah asisten yang menyusun catatan rapat dalam Bahasa Indonesia dari transkrip.
Aturan ketat:
- "overview": 2 sampai 4 kalimat tentang tujuan rapat, topik-topik utama yang dibahas, dan hasilnya. Jangan hanya mengulang judul rapat atau nama berkas; ceritakan isinya.
- Masukkan TASK untuk pekerjaan yang diminta, ditugaskan, diarahkan pimpinan, atau disanggupi dalam rapat (arahan seperti \
"ini harus kita siapkan sebelum akhir bulan" juga task; turunkan "confidence" bila penanggung jawab atau tenggatnya tidak \
jelas). Jangan mengarang task, nama, tanggal, atau durasi. Jika tidak disebutkan, isi null.
- "assignee": nama persis seperti yang diucapkan (bukan label SPEAKER). Null jika tidak ada penanggung jawab.
- "deadline_text": salin frasa tenggat PERSIS seperti diucapkan (mis. "Jumat depan"). Jangan hitung tanggal sendiri.
- "estimate_minutes": hanya jika durasi pengerjaan disebut; ubah ke menit.
- "evidence_time": salin penanda waktu [mm:ss] dari baris transkrip tempat task itu dibicarakan (tanpa kurung siku), \
dan "evidence_quote": kutipan singkat dari transkrip.
- "confidence": 0..1, turunkan bila tugas/penanggung jawab/tenggat ambigu.
- "key_points": 3 sampai 7 hal PALING penting yang perlu diingat atau dicatat oleh orang yang tidak hadir: topik utama, fakta, angka, kondisi, risiko, batas waktu, dan hal yang belum terjawab atau belum diputuskan. Masing-masing satu kalimat padat yang didukung transkrip (jangan menyimpulkan di luar yang diucapkan). Jangan mengulang keputusan dan task: keduanya punya bagian sendiri. Ini intisari, BUKAN rincian per waktu: jangan mengulang isi "minutes" satu per satu. Kosongkan jika rapat memang tidak memuat hal penting.
- "topics": SETIAP topik yang dibahas secara berarti, termasuk yang menyimpang dari agenda; jangan hanya agenda utama. Rapat sering melompat ke topik lain lalu kembali, kadang lupa kembali: gabungkan pembahasan topik yang sama walau terpisah waktu dan sebut waktunya di "times" (paling banyak 5 penanda waktu terpenting, disalin dari penanda waktu transkrip: awal, saat kembali dibahas, akhir). "status": "decided" bila ada keputusan atau kesimpulan; "open" bila dibahas tetapi belum selesai, ditunda, atau menunggu pihak lain; "dropped" bila diangkat lalu pembicaraan pindah dan topik itu tidak pernah dilanjutkan atau disimpulkan. "follow_up": apa yang masih harus dikerjakan atau diputuskan untuk topik itu (null bila sudah tuntas). "summary": satu sampai dua kalimat yang didukung transkrip.
- "decisions": hal yang disepakati, disimpulkan, dipilih, disetujui, atau arah yang ditetapkan, walaupun tidak diucapkan dengan kata "putuskan" atau "sepakat" (mis. "oke kita pakai vendor A", "berarti peluncuran digeser ke Senin", "setuju"). Satu kalimat yang menyebut apa yang diputuskan. Usulan, pertanyaan, atau pendapat yang belum disetujui BUKAN keputusan. Kosongkan jika memang tidak ada.
- "minutes": rincian jalannya rapat berurutan waktu, lebih detail daripada "key_points", dengan "time" disalin dari penanda waktu transkrip.
Balas HANYA JSON valid sesuai skema; tanpa teks lain."""

_MERGE_SYSTEM = """\
Kamu merapikan hasil ringkasan dari bagian-bagian transkrip satu rapat. Masukan berupa tiga daftar bernomor. Balas HANYA \
JSON dengan NOMOR saja, jangan menulis ulang isinya:
{"key_points": [nomor, ...], "decisions": [nomor, ...], "topics": [{"members": [nomor, ...], "status": "decided"|"open"|"dropped", "follow_up": str|null}]}
- "key_points": nomor poin yang dipilih untuk SELURUH rapat (paling banyak 10, yang terpenting, urut); buang duplikat dan yang remeh. \
Jangan memilih poin yang hanya mengulang keputusan.
- "decisions": nomor keputusan yang dipertahankan; buang hanya duplikat, jangan membuang keputusan yang berbeda.
- "topics": kelompokkan topik yang sama (dibahas di bagian berbeda, atau dibuka lagi setelah topik lain) dalam satu objek lewat \
"members" (semua nomornya). "status" adalah status AKHIR: "decided" bila pada akhirnya diputuskan atau disimpulkan (kecuali dibuka \
lagi tanpa kesimpulan), "open" bila terakhir masih menggantung, "dropped" bila hanya diangkat lalu tidak pernah dilanjutkan. \
"follow_up" mengikuti keadaan akhir (null bila tuntas). Setiap nomor topik muncul tepat satu kali.
"""

_SCHEMA_HINT = """\
Skema JSON:
{"overview": str, "key_points": [str],
 "topics": [{"title": str, "summary": str, "status": "decided"|"open"|"dropped", "times": ["mm:ss"], "follow_up": str|null}],
 "decisions": [str],
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


def _numbers(value, size: int) -> list[int]:
    """The valid, distinct 1-based numbers out of whatever the model returned, in its order."""
    out: list[int] = []
    for v in value if isinstance(value, list) else []:
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= size and v not in out:
            out.append(v)
    return out


def _pick(items: list[str], chosen, limit: int | None = None) -> list[str]:
    """The items the model chose (by number); all of them when it chose nothing usable."""
    nums = _numbers(chosen, len(items))
    picked = [items[i - 1] for i in nums] if nums else items
    return picked[:limit] if limit else picked


def _join_topics(topics: list[Topic], groups) -> list[Topic]:
    """One topic per group of numbers the model says are the same subject, with the status and follow-up it ended with.
    A topic no group mentions is kept as it was, so nothing is lost. Ordered by when each subject first came up."""
    seen: set[int] = set()
    out: list[Topic] = []
    for g in groups if isinstance(groups, list) else []:
        members = [i for i in _numbers(g.get("members"), len(topics)) if i not in seen]
        if not members:
            continue
        seen.update(members)
        parts = [topics[i - 1] for i in members]
        status = g.get("status") if g.get("status") in ("decided", "open", "dropped") else parts[-1].status
        times = sorted(dict.fromkeys(x for p in parts for x in p.times), key=lambda x: (parse_clock(x) is None, parse_clock(x) or 0))
        follow = g.get("follow_up") if "follow_up" in g else parts[-1].follow_up
        out.append(Topic(title=parts[0].title, summary=parts[-1].summary or parts[0].summary, status=status, times=times,
                         follow_up=follow if isinstance(follow, str) and follow.strip() else None))
    out += [tp for i, tp in enumerate(topics, 1) if i not in seen]
    return sorted(out, key=lambda tp: (parse_clock(tp.times[0]) is None, parse_clock(tp.times[0]) or 0) if tp.times else (True, 0))


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
    def _chat(self, messages: list[dict], *, structured: bool = True) -> str:
        for attempt in range(MAX_RETRIES + 1):
            body = {"model": self._model, "messages": messages, "temperature": 0.1}
            body["response_format"] = (
                {"type": "json_schema", "json_schema": {"name": "extraction", "schema": ExtractionResult.model_json_schema()}}
                if structured and self._json_schema_ok else {"type": "json_object"}
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
            if r.status_code == 400 and structured and self._json_schema_ok:
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
            if result.overview.strip() or result.key_points or result.topics or result.decisions or result.minutes or result.tasks:
                return result
            # Every field has a default, so "{}" validates. A meeting with words in it never has nothing to summarise:
            # it is a bad answer, not an empty one (it used to be saved as a blank summary and shown as "done").
            log.warning("LLM returned an empty extraction; raw reply: %r", raw[:300])
            last_err = "semua kolom kosong"
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": "Jawabanmu kosong. Isi overview, key_points, topics, decisions, minutes, dan tasks "
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

    def _merge_parts(self, parts: list[ExtractionResult]) -> tuple[list[str], list[str], list[Topic]]:
        """Parts of a long transcript are read one by one, so each returns its own key points (several parts, several
        sets of 3-7), its own decisions, and the subjects it saw: one raised early, dropped and picked up again later
        shows up in several parts, each with the status it had there. One more call joins them for the whole meeting.

        The model is asked for a SMALL answer, numbers only (which key points to keep, which topics are the same subject
        and how it ended); the text is assembled here. Rewriting every topic in full made the answer large enough for the
        provider to fail to produce valid JSON. Anything it does not mention is kept, and if the call fails altogether
        the plain lists stand: still true, only longer."""
        key_points = list(dict.fromkeys(k for p in parts for k in p.key_points))
        decisions = list(dict.fromkeys(d for p in parts for d in p.decisions))
        topics = [t for p in parts for t in p.topics]
        plain_topics = list({t.title.strip().lower(): t for t in topics}.values())
        if len(key_points) + len(decisions) + len(topics) < 2:
            return key_points, decisions, topics
        try:
            numbered = lambda items: "\n".join(f"{i}. {x}" for i, x in enumerate(items, 1))  # noqa: E731
            listing = (f"KEY_POINTS:\n{numbered(key_points)}\n\nDECISIONS:\n{numbered(decisions)}\n\nTOPICS:\n"
                       + numbered(f"[{t.status}] {t.title} | waktu: {','.join(t.times)} | tindak lanjut: {t.follow_up or '-'}"
                                  for t in topics))
            raw = self._chat([{"role": "system", "content": _MERGE_SYSTEM},
                              {"role": "user", "content": f"Hasil dari bagian-bagian transkrip (urut waktu):\n{listing}"}],
                             structured=False)
            answer = json.loads(_strip_fences(raw))
            return (_pick(key_points, answer.get("key_points"), limit=10), _pick(decisions, answer.get("decisions")),
                    _join_topics(topics, answer.get("topics")))
        except (LlmError, json.JSONDecodeError, ValidationError, AttributeError, TypeError, ValueError):
            log.warning("could not merge the parts of the transcript; keeping them as extracted", exc_info=True)
            return key_points, decisions, plain_topics

    # -- public --------------------------------------------------------------
    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        chunks = chunk_transcript(inp.transcript, self._chunk_chars)
        parts = [r for i, c in enumerate(chunks) for r in self._extract_fitting(inp, c, i + 1, len(chunks))]
        if len(parts) == 1:
            return parts[0]
        # Merge: tasks/decisions/minutes concatenate (the pipeline de-duplicates tasks);
        # the overview is rebuilt from the per-part overviews so it covers the whole meeting.
        key_points, decisions, topics = self._merge_parts(parts)
        merged = ExtractionResult(
            key_points=key_points,
            topics=topics,
            decisions=decisions,
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
