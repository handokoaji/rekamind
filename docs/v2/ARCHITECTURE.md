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

## Perekam Rust (`recorder/`)

Selama rapat hanya ada satu pekerjaan: menyalin audio ke disk. Tanpa ASR, VAD, diarisasi, atau jaringan.

| Aspek | Keputusan |
|---|---|
| Windows | WASAPI mode shared. Mikrofon = perangkat capture default; audio komputer = perangkat *render* default dibuka sebagai loopback. Windows sendiri mengonversi ke 16 kHz mono 16-bit (`autoconvert`), jadi jalur normal tidak melakukan DSP sama sekali |
| Cadangan Windows | Bila driver menolak, pakai format perangkat + resampler sendiri (windowed-sinc, tabel kernel; diukur 0,61% satu core pada build release) |
| Linux | Subproses `parec` (PulseAudio / PipeWire-pulse): tanpa header ALSA/libpulse, server suara yang me-resample |
| Polling, bukan event | Bangun ±10×/dtk per sumber (bukan ±100×) |
| Timeline | Loopback **tidak mengirim data saat komputer hening**. Tanpa penanganan, file speaker lebih pendek dan urutan transkrip kacau. Pengisi hening berbasis jam dinding menjaga kedua file satu garis waktu; saat Stop keduanya disamakan panjangnya |
| Tahan crash | Header WAV diperbarui tiap 2 dtk, penanda `session.json`, perintah `recover`; paling banyak ±2 dtk terakhir yang hilang |
| Perangkat berganti | Headset dicabut / perangkat default berganti → buka ulang otomatis; sumber yang gagal tidak menghentikan sumber lain |
| Tidak pernah kehilangan rekaman | Disimpan ke disk dulu; unggah gagal → kode keluar 2, rekaman aman, dan pesan menunjukkan perintah `upload` untuk mengulang |
| Ukuran | Biner release 1,7 MB (Linux), `opt-level=s`, LTO, `panic=abort` |

```bash
rekamind-rec record --server http://127.0.0.1:8787 --title "Rapat vendor" --name Andi --process --stats
rekamind-rec upload  <folder> --server ...      # unggah ulang rekaman yang tersimpan
rekamind-rec recover <folder>                   # perbaiki rekaman yang terhenti mendadak
rekamind-rec record --synthetic --duration 5    # nada uji tanpa perangkat audio
```

**Mengukur "ringan" di PC Anda:** CI membangun `rekamind-rec.exe` (artifact `rekamind-rec-windows`). Jalankan `record --stats` selama rapat sungguhan; di akhir ia mencetak CPU rata-rata dan memori puncaknya sendiri. Angka sintetis di Linux (0,67% CPU, 3,7 MB) **bukan** biaya WASAPI; itu hanya dasar overhead penulisan file.

## Aplikasi desktop (`desktop/`, Tauri 2)

Cangkangnya sengaja tipis: seluruh logika ada di `recorder/` (`controller`, `settings`, `local_backend`, `uploader`) dan diuji tanpa GUI. Lapisan Tauri hanya meneruskan perintah dan menampilkan `UiState`.

| Aspek | Keputusan |
|---|---|
| UI | SPA yang sama dengan versi web, ditanam di aplikasi. Komponen perekam hanya tampil di dalam Tauri; klien Tauri dimuat malas sehingga bundel browser tidak membayarnya |
| Kontrak Rust↔UI | Satu berkas emas `desktop/contract/ui-state.json` dihasilkan oleh tes Rust dan dibaca oleh tes web. Perubahan di salah satu sisi menggagalkan tes, bukan aplikasi |
| Keamanan | CSP ketat; hak IPC hanya untuk jendela `main` yang memuat aset lokal (tidak ada konten remote yang dapat memanggil IPC); URL server hanya http(s) |
| Selama rapat | Tidak ada yang berat. Backend lokal yang menganggur dimatikan saat rekaman mulai, dan **controller menolak menyalakannya lagi selama merekam**, apa pun yang diminta UI (invarian ini ditemukan lewat pengukuran: UI sempat menghidupkannya kembali). Unggahan rapat sebelumnya menunggu rapat yang sedang berjalan selesai. Permintaan data dijeda (bukan gagal) sehingga UI tidak menampilkan galat palsu |
| Setelah rapat | Backend lokal dinyalakan on-demand untuk unggah dan pemrosesan, lalu dimatikan setelah menganggur 10 menit (membebaskan RAM dan GPU) |
| Indikator rekaman | Bilah merah di setiap halaman, ikon tray merah, judul jendela "● Merekam", notifikasi; kartu perekam menampilkan level mic dan audio komputer dan menyatakan sumber yang bermasalah dengan kata-kata |
| Jendela | Ditutup = **dihancurkan** (bukan disembunyikan): WebView adalah bagian terberat, jadi selama rapat dengan jendela tertutup yang hidup hanya proses shell. Dibuka lagi dari tray atau peluncuran kedua (single-instance). `--hidden` memulai langsung ke tray tanpa jendela |
| Tidak mudah terhenti | Menutup jendela tidak mengakhiri rekaman maupun aplikasi (selama tray ada); Stop memakai dialog konfirmasi; hotkey/tray berhenti langsung |
| Penutupan | Keluar, logout, `SIGTERM`: file WAV ditutup dengan benar dan rekaman tetap ada sebagai "belum terunggah" |
| Pemulihan | Rekaman yang tidak sempat terunggah, atau terhenti oleh crash, tampil di daftar "belum terunggah" dengan tombol Unggah dan Hapus (dengan konfirmasi) |
| Tray tidak ada | Aplikasi tetap berjalan tanpa tray (diuji: sandbox tanpa D-Bus) |

**Diukur** (rilis, Linux/WebKitGTK, PSS, audio sintetis, jadi tanpa biaya perangkat audio asli):

| Keadaan | Memori |
|---|---|
| Jendela terbuka, menganggur, backend lokal menyala | ±319 MB (shell 76 + WebKit 153 + Python 90) |
| **Merekam, jendela terbuka**, backend mati | ±240 MB |
| **Merekam, jendela ditutup**, backend mati | **±79 MB** (hanya shell; tanpa WebKit, tanpa Python) |
| Perekam CLI saja (`rekamind-rec`) | ±3,7 MB |

Sisa 79 MB pada shell sebagian besar adalah pustaka GTK/WebKit yang ter-link di Linux. Di Windows (Win32 native + WebView2 di luar proses) angkanya bisa sangat berbeda: **ukur di PC Anda**. Bila ternyata terlalu besar, opsinya memisahkan perekam menjadi proses agen kecil terpisah dari shell; keputusan itu sebaiknya menunggu angka Windows.

**Diverifikasi** (Linux, WebKitGTK di X11 virtual, backend Python asli): UI tampil di WebView; `Ctrl+Alt+R` global memulai/menghentikan rekaman; level mic/speaker bergerak; unggah ke backend yang dinyalakan on-demand; rapat baru muncul otomatis di daftar; `SIGTERM` saat merekam menghasilkan WAV valid.

**Belum diverifikasi** (perlu Windows): WebView2 dan asal `http://tauri.localhost` untuk CORS, tray dan notifikasi Windows, pintasan global di Windows, WASAPI sungguhan, installer NSIS (CI membangunnya; belum pernah berjalan), perilaku saat sesi Windows berakhir.

**Keterbatasan yang harus Anda tahu:** mode lokal memanggil `python -m rekamind_server` (dapat diubah di Pengaturan); belum ada backend terbundel di installer, jadi "instalasi mudah" baru terpenuhi untuk mode server terpisah (Docker). Membundelnya (PyInstaller/ONNX) adalah pekerjaan terpisah yang ukurannya bergantung pada hasil benchmark engine.

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
- **Login Google wajib** (`REKAMIND_AUTH=google`): isi `REKAMIND_GOOGLE_CLIENT_ID/SECRET`, `REKAMIND_PUBLIC_URL`, `REKAMIND_SUPERADMINS` (lihat `docs/AUTH.md`). Server menolak start bila tidak diisi. Pasang di belakang reverse proxy HTTPS.
- GPU di Docker (NVIDIA Container Toolkit) ditambahkan bersamaan dengan engine nyata. AMD/Vulkan di dalam container lebih rumit dan belum dievaluasi.
- Image (backend + UI) sudah dibangun dan dijalankan di sandbox: non-root, healthcheck `healthy`, UI tersaji, 5 tes E2E lolos terhadap container, memori idle ±72 MiB. Dua catatan jujur: sandbox memakai CA proxy sementara (build normal tidak memerlukannya) dan tahap Node pada Dockerfile tidak bisa dibangun di sana karena Docker Hub membatasi penarikan image `node` (429); langkahnya (`npm ci && npm run build`) diuji terpisah di salinan bersih.

## Status

| Fase | Isi | Status |
|---|---|---|
| 0 | Benchmark engine pada rekaman Indonesia nyata | Alat siap (`python -m rekamind_server.bench`); **menunggu dijalankan di PC Anda** |
| 1 | Inti backend: model, antrean job, pipeline, API, task terstruktur | Selesai (72 tes) |
| 1b | Engine: faster-whisper, pyannote, LLM OpenAI-compatible | Ditulis; **model/GPU belum teruji** (hanya stub) |
| 1c | Penyimpanan S3 (MinIO/SeaweedFS/AWS), Alembic | Selesai. Diuji ke SeaweedFS asli (Docker) dan moto; Postgres 16 asli (12 rapat serentak, migrasi 0001→0002 dengan data, dua migrasi bersamaan, 8 E2E auth). **MinIO asli belum** (image tidak tersedia di sandbox) |
| 2 | SPA React (daftar rapat, detail, review task, transkrip, pembicara, pengaturan) | Selesai: 15 tes unit, 5 tes E2E, axe WCAG AA bersih (terang/gelap), tanpa scroll horizontal di 375 px |
| 3a | Perekam Rust (`recorder/`): library + CLI `rekamind-rec` | Selesai di sisi kode: 33 tes lolos di Linux; kode Windows (WASAPI) ter-compile terhadap API aslinya tetapi **belum pernah dijalankan**. Lihat "Perekam Rust" |
| 3b | Shell Tauri: jendela, tray, pintasan global, notifikasi, backend lokal on-demand | Selesai dan **dijalankan sungguhan di Linux** (WebKitGTK + X11): hotkey, rekam, unggah, SIGTERM. **Belum dijalankan di Windows** (WebView2, tray, NSIS) |
| 3c | Backend lokal terbundel di installer (sidecar PyInstaller) + mesin transkripsi dipasang saat dibutuhkan | Selesai dan **dijalankan sungguhan di Linux** dari paket `.deb`: backend beku menjalankan pipeline penuh, pemasangan mesin CPU dari dalam aplikasi (progres langsung, 13 dtk, `Uji mesin` lulus), mati sendiri bila aplikasi dimatikan paksa. `.deb` 127 MiB (backend 258 MB tak terkompresi; 100 MB di antaranya ffmpeg milik PyAV). **Belum**: Windows (installer NSIS, jalur panjang, cuDNN), GPU NVIDIA, model Whisper (HF diblokir di sandbox) |
| 4a | Autentikasi: login Google (OIDC+PKCE), user hanya melihat miliknya, super admin, login desktop | Selesai: 141 tes server, 46 tes unit web, 8 E2E auth (termasuk CLI Rust lintas proses), 79 tes Rust. **Google asli dan Credential Manager Windows belum dicoba** (lihat `docs/AUTH.md`) |
| 4b | Mode remote: worker GPU dengan kredensial layanan, unggah presigned URL | **Belum** |
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
- Login Google belum dicoba terhadap Google asli, hanya terhadap IdP tiruan (lihat `docs/AUTH.md`).

## Pengujian: apa yang sudah dibuktikan

Dibuktikan di sandbox (Linux, tanpa GPU): 49 tes unit/API; alur penuh lewat HTTP dengan worker bawaan; Postgres 16 sungguhan (klaim job bersamaan: 1 pemenang dari 6); container Docker non-root dengan data bertahan setelah restart; lint ruff bersih.

Ditunda ke akhir (butuh PC/GPU): kecepatan dan akurasi model nyata (`python -m rekamind_server.bench`), faster-whisper/pyannote asli, perekam Rust di Windows (CPU/RAM saat merekam), installer, latensi end-to-end.

## Autentikasi

Sudah dikerjakan dan diuji: login Google (OIDC + PKCE) dengan kredensial milik pemasang, user hanya melihat
rapat miliknya, super admin bisa semuanya, login desktop lewat browser sistem. Rincian, cara membuat OAuth
client, dan batas pembuktian ada di [`docs/AUTH.md`](../AUTH.md). Rencana awal yang berbasis OAuth UGM
dibatalkan (proyek ini open source, jadi tidak boleh bergantung pada satu IdP kampus); UGM bisa menjadi
penyedia kedua di masa depan.
