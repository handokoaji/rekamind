# Rekamind v2 — arsitektur dan rencana

Status: **rencana + inti backend (Fase 1 sebagian)**. Kode `app/` lama (Tkinter) belum disentuh.

## Syarat yang mengikat desain

1. **Saat rapat, perekam harus nyaris tak terasa.** Hanya capture + tulis ke disk. Tidak ada ASR, VAD, atau diarisasi.
2. **Proses berat setelah rapat**, di GPU lokal atau di server backend terpisah.
3. **Instalasi mudah:** aplikasi = installer sekali klik; backend = `docker compose` / stack Portainer.
4. Backend yang sama untuk mode lokal dan remote (bedanya hanya URL).
5. Task hasil rapat harus terstruktur dan **dikonfirmasi manusia** sebelum diekspor ke task manager.

## Komponen

```
┌────────────── Desktop (Tauri 2 + Rust) ──────────────┐        ┌───────────── Backend (Python/FastAPI) ─────────────┐
│ UI: React + Vite + TS + Tailwind + shadcn/ui         │  HTTP  │ API ── antrean job (tabel DB) ── Worker            │
│ Perekam Rust: WASAPI loopback + mic → WAV 16 kHz mono│ ─────▶ │ Engines: transcriber / diarizer / extractor (LLM)   │
│ Tray, hotkey global, deteksi aplikasi rapat          │        │ DB: SQLite (lokal) | Postgres (server)              │
└──────────────────────────────────────────────────────┘        │ Storage: disk lokal | S3 (MinIO/SeaweedFS)          │
   mode lokal: backend dijalankan on-demand setelah rapat        └────────────────────────────────────────────────────┘
   mode remote: backend di VM GPU (Docker), desktop hanya unggah audio
```

Keputusan penting:
- **Perekam di Rust, tanpa Python**, supaya selama rapat tidak ada runtime Python/torch yang hidup. Backend Python lokal baru dijalankan saat "Proses" dan dimatikan setelah menganggur.
- **Satu SPA** dipakai di shell Tauri dan dilayani backend untuk akses web (lihat hasil/task dari browser lain).
- **Pemisahan engine** lewat kontrak `Transcriber / Diarizer / Extractor` (`server/rekamind_server/engines/base.py`): CUDA (faster-whisper), Vulkan (whisper.cpp, untuk AMD/Intel), OpenVINO, atau worker remote ditukar tanpa mengubah pipeline.
- **Diarisasi hanya untuk kanal speaker.** Kanal mic selalu pengguna lokal.
- **Tidak ada transkrip live.** Gantinya indikator level mic/speaker dan durasi.
- **Task** punya bukti (timestamp + kutipan), skor confidence, dan status `suggested → confirmed | rejected`. Tanggal deadline dihitung deterministik dari frasa (`deadlines.py`), bukan oleh LLM; frasa yang samar ditandai `approximate`.
- Tidak ada sinkronisasi DB dua arah di v1: satu rapat hidup di satu backend.

## Perekam Rust (belum dibuat)

- Capture: crate `wasapi` (loopback + mic, event-driven). Linux: monitor source PulseAudio/PipeWire — **perlu diverifikasi** crate mana yang paling andal.
- Resample ke 16 kHz mono 16-bit, tulis per-sumber (`mic`, `speaker`) dalam potongan beberapa menit supaya crash hanya kehilangan beberapa detik terakhir.
- Tangani pencabutan headset / pergantian perangkat default tanpa menghentikan rekaman.
- Target CPU/RAM saat merekam: **diukur, bukan diasumsikan** (target awal: <2% CPU, <60 MB — belum terbukti).

## Menjalankan backend

```bash
docker compose up -d --build        # atau tempel docker-compose.yml sebagai stack di Portainer
```
- Default: SQLite di volume `rekamind-data`; port hanya di `127.0.0.1`.
- **Belum ada autentikasi.** Jangan buka ke jaringan tanpa reverse proxy ber-auth. Auth dikerjakan setelah MVP.
- GPU di Docker (NVIDIA Container Toolkit) ditambahkan bersamaan dengan engine nyata. AMD/Vulkan di dalam container lebih rumit dan belum dievaluasi.
- Image belum pernah di-build di lingkungan pengembangan ini (tidak ada daemon Docker); hanya sintaks compose yang divalidasi.

## Status

| Fase | Isi | Status |
|---|---|---|
| 0 | Benchmark engine pada rekaman Indonesia nyata | **Menunggu rekaman contoh** |
| 1 | Inti backend: model, antrean job, pipeline, API, task terstruktur, Docker | Sebagian: 33 tes lolos, engine nyata belum ada (hanya `fake`) |
| 1b | Engine nyata (faster-whisper, pyannote/sherpa-onnx, Groq/OpenAI-compatible), S3, Alembic | Belum |
| 2 | SPA React (riwayat, detail, review task, pengaturan) | Belum |
| 3 | Shell Tauri + perekam Rust + installer | Belum |
| 4 | Mode remote: worker GPU, unggah presigned URL, autentikasi | Belum |
| 5 | Integrasi task manager (webhook dulu, API Anda menyusul) | Belum |

## Usulan fitur tambahan

Diurutkan menurut nilai/biaya. Yang bertanda ⚠ punya risiko yang perlu keputusan Anda.

**Prioritas tinggi (langsung memperbaiki tujuan utama)**
1. **Kosakata khusus (glosarium):** nama orang, proyek, istilah internal dimasukkan sebagai prompt awal Whisper dan koreksi pasca-LLM. Biasanya dampak terbesar untuk akurasi rapat bisnis, termasuk campuran Indonesia–Inggris. Perlu diukur di rekaman Anda.
2. **Integrasi kalender (ICS/Google/Outlook):** judul dan daftar peserta terisi otomatis, sehingga PIC bisa dicocokkan ke nama nyata, bukan `SPEAKER_01`.
3. **Pemutar audio tersinkron:** klik kalimat atau bukti task → audio loncat ke momen itu. Ini cara tercepat bagi pengguna memverifikasi hasil LLM.
4. **Tindak lanjut task antar-rapat:** di awal rapat serial, tampilkan task yang masih terbuka dari rapat lalu; saat transkrip berisi "laporannya sudah selesai", usulkan menutup task tersebut.
5. **Deteksi aplikasi rapat + hotkey global:** notifikasi "Zoom/Teams/Meet aktif — mulai rekam?" lewat enumerasi sesi audio, dan satu hotkey untuk mulai/stop.
6. **Penjaga sumber daya untuk pemrosesan lokal:** tunda proses berat saat laptop di baterai atau CPU/GPU sibuk, jalankan dengan prioritas rendah, tampilkan estimasi waktu.
7. **Pencarian lintas rapat** (FTS5 di SQLite, tsvector di Postgres) dengan lompatan ke timestamp.

**Prioritas menengah**
8. **Webhook keluar yang kokoh** ke task manager Anda: payload berversi, tanda tangan HMAC, kunci idempotensi, retry; lalu sinkron status dua arah bila API-nya sudah ada.
9. **Worker remote model "tarik"**: server GPU yang menarik job dari API sehingga tidak perlu membuka port masuk (aman di balik NAT/firewall).
10. **Retensi dan privasi:** hapus audio otomatis setelah N hari tetapi pertahankan transkrip, enkripsi saat disimpan di S3, banner persetujuan merekam.
11. **Penanda segmen berkeyakinan rendah** ("perlu dicek") di transkrip.
12. **Ekspor:** docx (sudah ada di v1), PDF, Markdown, dan draf pesan WhatsApp/email berisi ringkasan + task.

**Opsional**
13. ⚠ **Sidik suara untuk pengenalan pembicara otomatis lintas rapat.** Bermanfaat, tetapi itu data biometrik; harus opt-in per orang dan dihapus bila diminta.
14. ⚠ **Tanya-jawab atas riwayat rapat (RAG)** dengan kutipan timestamp. Menarik, tetapi baru bernilai setelah riwayat cukup besar dan menambah ketergantungan LLM/embedding.

**Sengaja tidak diusulkan:** bot yang bergabung ke rapat (rapuh, melanggar ekspektasi privasi), terjemahan real-time, perekaman video.

## Risiko terbuka

- Akurasi ASR/diarisasi bahasa Indonesia belum diukur; pilihan model masih hipotesis sampai Fase 0.
- Dukungan GPU AMD/Intel lewat Vulkan belum diuji; jalur NVIDIA adalah satu-satunya yang terbukti di proyek ini.
- Alembic (migrasi skema) belum dipasang; sekarang `create_all`. Wajib sebelum rilis pertama.
- Tanpa autentikasi, backend hanya aman di loopback.
