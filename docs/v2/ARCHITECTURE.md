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

## Pengembangan

```bash
# backend (SQLite, engine tiruan)
pip install -e "server[dev]" && REKAMIND_ENGINES=fake python -m rekamind_server     # :8787
# UI dengan hot reload, proxy /api ke backend di atas
cd web && npm ci && npm run dev
# tes
pytest server -q                  # backend
cd web && npx vitest run          # unit UI
cd web && npx playwright test     # E2E: backend asli + build produksi (perlu: npx playwright install chromium)
```

## Menjalankan backend

```bash
docker compose up -d --build        # atau tempel docker-compose.yml sebagai stack di Portainer
```
- Default: SQLite di volume `rekamind-data`; port hanya di `127.0.0.1`.
- **Belum ada autentikasi.** Jangan buka ke jaringan tanpa reverse proxy ber-auth. Auth dikerjakan setelah MVP.
- GPU di Docker (NVIDIA Container Toolkit) ditambahkan bersamaan dengan engine nyata. AMD/Vulkan di dalam container lebih rumit dan belum dievaluasi.
- Image (backend + UI) sudah dibangun dan dijalankan di sandbox: non-root, healthcheck `healthy`, UI tersaji, 5 tes E2E lolos terhadap container, memori idle ±72 MiB. Dua catatan jujur: sandbox memakai CA proxy sementara (build normal tidak memerlukannya) dan tahap Node pada Dockerfile tidak bisa dibangun di sana karena Docker Hub membatasi penarikan image `node` (429); langkahnya (`npm ci && npm run build`) diuji terpisah di salinan bersih.

## Status

| Fase | Isi | Status |
|---|---|---|
| 0 | Benchmark engine pada rekaman Indonesia nyata | Alat siap (`python -m rekamind_server.bench`); **menunggu dijalankan di PC Anda** |
| 1 | Inti backend: model, antrean job, pipeline, API, task terstruktur | Selesai (72 tes) |
| 1b | Engine: faster-whisper, pyannote, LLM OpenAI-compatible | Ditulis; **model/GPU belum teruji** (hanya stub) |
| 1c | Penyimpanan S3 (MinIO/SeaweedFS/AWS), Alembic | Selesai. S3 diuji ke server S3 tiruan di socket (moto); **MinIO/SeaweedFS asli belum** |
| 2 | SPA React (daftar rapat, detail, review task, transkrip, pembicara, pengaturan) | Selesai: 15 tes unit, 5 tes E2E, axe WCAG AA bersih (terang/gelap), tanpa scroll horizontal di 375 px |
| 3 | Shell Tauri + perekam Rust + installer | **Belum** |
| 4 | Mode remote: worker GPU, unggah presigned URL, autentikasi | **Belum** |
| 5 | Integrasi task manager (webhook dulu, API Anda menyusul) | **Belum** (ekspor JSON `rekamind.tasks/v1` sudah ada di UI) |

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
- Tanpa autentikasi, backend hanya aman di loopback.

## Pengujian: apa yang sudah dibuktikan

Dibuktikan di sandbox (Linux, tanpa GPU): 49 tes unit/API; alur penuh lewat HTTP dengan worker bawaan; Postgres 16 sungguhan (klaim job bersamaan: 1 pemenang dari 6); container Docker non-root dengan data bertahan setelah restart; lint ruff bersih.

Ditunda ke akhir (butuh PC/GPU): kecepatan dan akurasi model nyata (`python -m rekamind_server.bench`), faster-whisper/pyannote asli, perekam Rust di Windows (CPU/RAM saat merekam), installer, latensi end-to-end.

## Autentikasi (rencana, belum dikerjakan)

Sumber: `openapi.json` "UGM ID 2.0" yang Anda berikan. Server asli tidak bisa dijangkau dari sandbox, jadi **semua di bawah ini belum diuji terhadap server sungguhan**.

Yang dipakai: OAuth 2.0 murni. Tidak memakai OIDC (discovery, `id_token`, `/userinfo`) maupun PKCE, sesuai arahan Anda.

| Kebutuhan | Endpoint / grant dari dokumen |
|---|---|
| Validasi token | `POST /oauth/introspect` (Basic auth client; RFC 7662). Hanya client penerbit token yang boleh mengintrospeksinya |
| Identitas | Respons introspeksi: `sub` (username), `data.email`, `data.unit_id`, `scope`, `exp` |
| Profil | `GET /api/me` (scope `user.read`) |
| Cabut sesi | `POST /oauth/revoke` |
| Worker GPU → API | `client_credentials` |

Pola yang disarankan: **backend Rekamind menjadi confidential client (BFF)**. Browser/aplikasi desktop tidak pernah memegang `client_secret`; backend yang menukar kode, memvalidasi token lewat introspeksi (cache ≤60 dtk), dan memberi sesi miliknya sendiri. Ini juga memenuhi aturan introspeksi di atas.

Ganjalan yang perlu Anda putuskan:
1. Dokumen menyatakan `/oauth/authorize` **mewajibkan** `code_challenge` (PKCE), sedangkan PKCE belum bisa dipakai. Selama itu, alur Authorization Code kemungkinan tidak dapat dipakai.
2. Tersisa grant `password` (kredensial LDAP dikirim ke backend kita). Itu jalan pintas yang menempatkan kata sandi UGM pengguna di aplikasi kita dan dihapus dari OAuth 2.1; saya hanya akan memakainya bila Anda menyetujuinya secara eksplisit.
3. Perlu: `client_id`/`client_secret`, redirect URI terdaftar, scope yang diizinkan, dan akses ke server dev (`oauth.dev.ugm.ac.id`) untuk pengujian.
