# Meeting Recorder & AI Summarizer — Design Spec

Date: 2026-07-30

## 1. Purpose

Aplikasi desktop Windows untuk merekam audio rapat online (Google Meet, Zoom,
MS Teams — atau apa saja) langsung dari speaker + mic komputer, mentranskrip
percakapan Bahasa Indonesia secara near-real-time dengan pemisahan pembicara
(speaker diarization), lalu menghasilkan Minutes of Meeting (MoM) yang detail
lewat Groq LLM. Harus jalan efisien di dua mesin berbeda: desktop dengan GPU
NVIDIA GTX 1080 Ti, dan laptop dengan Intel Core Ultra 7 155H (NPU + Arc GPU).

Aplikasi tidak berintegrasi dengan Google Meet/Zoom/Teams secara spesifik —
murni merekam apa pun yang keluar dari speaker (loopback) dan mic sistem,
agnostik terhadap aplikasi meeting yang dipakai.

## 2. Hardware & Platform

- OS: Windows only.
- Runtime: Python (venv sudah ada di repo, Python 3.14).
- Dua target hardware, terdeteksi otomatis saat startup (bisa di-override lewat env var):
  - Desktop: NVIDIA GTX 1080 Ti → backend CUDA.
  - Laptop: Intel Core Ultra 7 155H → backend OpenVINO (GPU/NPU Intel).
- Constraint keras: aplikasi tidak boleh membebani RAM/CPU/GPU secara
  signifikan selama idle atau saat live recording, walau kedua mesin punya
  32GB RAM. Model besar hanya boleh dimuat sebentar untuk proses batch,
  tidak menetap di memori selama rapat berlangsung.

## 3. Prinsip Utama: ASR Dua Tahap

Karena "real-time & ringan" dan "akurasi transkrip mendekati maksimal" saling
tarik-menarik pada ukuran model yang sama, sistem memakai dua tahap ASR
dengan tujuan berbeda:

1. **Live preview** (selama rapat berlangsung): model ASR ukuran `small`
   (sama di kedua mesin, cukup ringan untuk real-time di CUDA maupun
   OpenVINO GPU/NPU), untuk teks yang muncul near-real-time di window
   monitoring. Prioritas: latensi rendah & RAM kecil, bukan akurasi maksimal.
2. **Transkrip final** (setelah rekaman berhenti): model `large-v3` dijalankan
   ulang secara batch dari file audio penuh, di KEDUA mesin (tidak dibatasi
   real-time factor karena rapat sudah selesai). Hasil ini yang disimpan
   sebagai transkrip resmi dan dipakai untuk generate MoM. Model dilepas dari
   memori setelah selesai.

Diarization (pemisah pembicara) hanya berjalan pada stream speaker/loopback
(mic = selalu "Anda", karena mic hanya menangkap satu pengguna lokal).
Diarization berjalan pada buffer rolling ~8 detik menggunakan
`pyannote.audio` (speaker-diarization-3.1), sehingga label pembicara muncul
beberapa detik setelah teks (near-real-time, bukan real-time murni per kata)
— jauh lebih ringan dibanding diarization streaming penuh.

## 4. Komponen

```
app/
  main.py                  # entrypoint: tray icon + background pipeline
  config.py                # baca .env (pydantic-settings)
  audio/
    capture.py             # WASAPI mic + speaker loopback (pyaudiowpatch)
    vad.py                  # segmentasi ucapan (silero-vad)
  asr/
    base.py                 # interface TranscriberBackend
    cuda_backend.py          # faster-whisper + CUDA (desktop)
    openvino_backend.py      # optimum-intel / OpenVINO (laptop NPU/GPU)
    detect.py                # auto-deteksi hardware saat startup
  diarization/
    diarizer.py              # pyannote.audio, rolling buffer 8 detik
  pipeline/
    session.py               # orkestrasi live: capture -> VAD -> ASR kecil -> diarization -> UI
    finalize.py               # post-processing batch: re-transcribe large-v3 + merge + trigger summary
  summarization/
    groq_client.py             # panggil Groq (llama-3.3-70b-versatile), generate MoM
    docx_export.py              # export MoM ke .docx rapi (python-docx)
  storage/
    db.py, models.py            # SQLAlchemy async + Postgres
  ui/
    window.py                    # Tkinter: monitoring live transcript, kontrol, riwayat
  tray/
    icon.py                       # pystray: Mulai Meeting / Stop / Buka Monitor / Keluar
```

Tidak ada web server/browser di aplikasi ini — seluruh UI berjalan native lewat
Tkinter agar tidak menambah proses/RAM browser.

## 5. Data Flow

1. User klik tray icon → "Mulai Meeting" → window Tkinter kecil muncul untuk
   isi judul meeting + (opsional) waktu terjadwal.
2. Klik "Mulai Rekam": audio mic & speaker ditangkap paralel via WASAPI,
   disimpan sebagai file WAV permanen di `./recordings/<meeting_id>/`.
3. VAD memecah audio jadi segmen ucapan → dikirim ke model ASR kecil (live) →
   teks partial tampil di window Tkinter lewat queue thread-safe (poll ~100ms).
4. Tiap ~8 detik, buffer speaker stream di-diarize → label Speaker 1/2/3
   ditempel ke segmen sesuai timestamp, tampil menyusul di window.
5. Klik "Stop Rekam": mencatat waktu selesai, menutup capture.
6. Proses finalisasi (background): re-transcribe seluruh file audio dengan
   model large-v3 → transkrip final (mic="Anda" + speaker berlabel) disusun
   kronologis → disimpan ke DB → dikirim ke Groq → hasil MoM (ringkasan
   menit-per-menit, keputusan, action items, catatan detail) disimpan ke DB
   dan di-export ke `.docx` rapi.
7. User bisa rename "Speaker 1" → nama asli kapan saja dari window riwayat.
8. Window riwayat menampilkan daftar meeting lalu (dari Postgres), buka
   transkrip/MoM, buka file .docx.

## 6. Skema Database (Postgres `meeting_recorder`)

Server: `10.55.11.209:5432`, kredensial di `.env` (`POSTGRES_*`,
`DATABASE_URL`). Database `meeting_recorder` sudah dibuat.

- `meetings`: id, title, scheduled_time (nullable), start_time, end_time, status (`scheduled|recording|processing|completed|failed`), created_at
- `speakers`: id, meeting_id (FK), label (`Speaker 1`, `Anda`, dst), display_name (nullable)
- `transcript_segments`: id, meeting_id (FK), speaker_id (FK), source (`mic|speaker`), start_ms, end_ms, text, is_final (live vs hasil final large-v3)
- `recordings`: id, meeting_id (FK), file_path, source (`mic|speaker`), duration_ms
- `summaries`: id, meeting_id (FK), mom_json, docx_path, groq_model, status (`pending|ready|failed`), created_at

## 7. Konfigurasi (.env)

```
POSTGRES_HOST=10.55.11.209
POSTGRES_PORT=5432
POSTGRES_USER=admin
POSTGRES_PASSWORD=admin
POSTGRES_DB=meeting_recorder
DATABASE_URL=postgresql+asyncpg://admin:admin@10.55.11.209:5432/meeting_recorder
GROQ_API_KEY=            # diisi manual oleh user
HF_TOKEN=                # diisi manual oleh user (butuh accept terms pyannote di HuggingFace)
```

`.env` tidak boleh pernah masuk git (sudah di `.gitignore`).

## 8. UI (Tkinter, Bahasa Indonesia)

- Tanpa autentikasi (single-user, native window, tidak exposed ke jaringan).
- Tanpa auto-start di Windows boot (dijalankan manual untuk MVP).
- Window utama: status rekam, live transcript (scrollable text), tombol
  Mulai/Stop.
- Window riwayat: daftar meeting, buka transkrip/MoM, rename speaker, buka
  file .docx hasil export.

## 9. Error Handling

- Device audio (mic/speaker) tidak ditemukan → gagal start dengan pesan jelas
  di window, tidak membuat entry meeting kosong.
- Model ASR gagal dimuat di GPU/NPU (driver/OOM) → fallback ke CPU, catat
  warning di log, tetap jalan (lebih lambat, bukan mati total).
- Groq API gagal/timeout → status summary `failed`, bisa di-retry manual dari
  window riwayat, transkrip tetap tersimpan utuh.
- File WAV mentah adalah source of truth di disk. Jika penulisan ke Postgres
  gagal saat rekam, retry dicatat di log; audio tetap bisa diproses ulang
  kapan saja dari file karena tidak dihapus otomatis.

## 10. Testing

- Unit test pipeline audio→VAD→segmentasi memakai file WAV contoh yang sudah
  direkam (tanpa perlu hardware capture asli tiap kali test).
- Unit test merge logika transcript_segments + speaker label berdasarkan
  timestamp overlap.
- Smoke test hardware-detect: memastikan fallback CPU jalan kalau CUDA/OpenVINO
  tidak terdeteksi.
- Smoke test koneksi DB & Groq client (mock response untuk Groq di test).

## 11. Fase Implementasi

1. **Fase 1 — Fondasi**: capture mic+speaker ke WAV, skema DB + koneksi,
   window Tkinter dasar (start/stop, isi judul), pipeline batch: setelah stop
   rekam baru transcribe (large-v3) + diarize + generate summary + export
   docx. Belum ada live preview real-time.
2. **Fase 2 — Real-time**: tambahkan model ASR kecil untuk live preview +
   VAD streaming + diarization rolling buffer, tampil live di window Tkinter.
3. **Fase 3 — Polish**: rename speaker dari UI, window riwayat meeting,
   retry manual untuk summary gagal, penyempurnaan format .docx.

## 12. Di Luar Scope (Eksplisit)

- Tidak ada integrasi API resmi Zoom/Meet/Teams (deteksi platform/judul
  window) — murni capture audio generik.
- Tidak ada autentikasi UI, tidak ada akses jaringan/LAN ke UI.
- Tidak ada auto-start Windows boot.
- Tidak ada packaging ke installer/.exe (dijalankan dari venv Python untuk
  sekarang).
- Tidak ada dukungan Linux/macOS.
