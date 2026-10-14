# Hasil uji di PC (Windows 11 + GTX 1080 Ti)

Diuji 2026-10-15, branch `v2/core-api` @ `f04f9e1`+pull (`PC_TEST_PROMPT.md`). Mesin uji: Windows 11 Education 10.0.26300,
GTX 1080 Ti 11 GB (driver 582.66), RAM 32 GB, Python 3.13, Node 25.2, Rust 1.99 (MSVC), Docker 29.8.
Bahan uji: rekaman nyata dari `recordings/` (format v1: `mic.wav` 16 kHz mono + `speaker.wav` 48 kHz stereo).
Tidak ada perbaikan kode yang dilakukan; berkas ini hanya laporan. Perbaikan ada di bagian **Yang harus diperbaiki**.

Legenda: LULUS / GAGAL / SEBAGIAN / TIDAK DIUJI (alasan).

## 1. Ringkasan

| Area | Status |
|---|---|
| Build installer NSIS di Windows | LULUS (313 dtk, 52,5 MB, belum ditandatangani) |
| Smoke test backend beku | LULUS (12 "ok") |
| Perekam: WASAPI loopback + mic nyata | LULUS (CPU 0,10 %, 11 MB) |
| App terpasang: hotkey, tutup jendela, unggah otomatis | LULUS |
| **Pasang mesin dari dalam app (backend beku)** | **GAGAL** (distlib/pip beku) |
| **Diarisasi pyannote di backend beku** | **GAGAL** (`pickletools`) |
| **Transkripsi pada pack yang dipasang segar** | **GAGAL** (`av` 19 vs faster-whisper 1.2.1) |
| Ekstraksi LLM pada rapat panjang (Groq 8000 TPM) | **GAGAL** (413, seluruh job gagal) |
| `cargo test` perekam di Windows | 2 GAGAL dari 15 di `controller_tests` (1 = bug data-loss) |
| `pytest server` di Windows | LULUS (155) |
| Postgres 16 + SeaweedFS asli (butir 15–16) | LULUS |
| MinIO asli | TIDAK DIUJI (image tidak bisa ditarik) |
| Google asli (butir 14) | TIDAK DIUJI (butuh akun/OAuth client) |

## 2. Hasil per butir (PC_TEST_PROMPT / CHECKLIST)

| Butir | Status | Bukti | Catatan |
|---|---|---|---|
| 0b build | LULUS | `build_desktop.py` exit 0, 313 dtk; `Rekamind_0.0.1_x64-setup.exe` 52,5 MiB; backend beku 146 MB | Peringatan NSIS: bahasa Indonesia tidak ada terjemahan pesan Tauri. Node 25 dipakai (dokumen minta 22), tidak masalah |
| Smoke backend | LULUS | `smoke_backend.py` → "Smoke test lulus." (12 ok) | Smoke hanya memeriksa "pip is bundled", **bukan** bahwa pip bisa dijalankan (lihat temuan 1) |
| A1 pasang | LULUS | `/S` exit 0, 6 dtk, ke `%LOCALAPPDATA%\Rekamind` (per-pengguna, tanpa admin) | `Get-AuthenticodeSignature` = NotSigned. Tidak diuji dengan SmartScreen interaktif |
| A2 buka | SEBAGIAN | Jendela "Rekamind" ada, backend menyala, migrasi jalan, `backend.log` terisi | Ikon tray dan jendela konsol berkedip **tidak bisa saya lihat** (tanpa layar). Lihat temuan 9 soal polling kesehatan |
| A3 hotkey+rekam, jendela tertutup | LULUS | `Ctrl+Alt+R` (keybd_event) mulai/berhenti; WAV 59,7 dtk; `uploaded.json` ada; `POST /process` → 503 (mesin belum ada, sesuai harapan) | Jendela ditutup: WebView2 anak 0; `rekamind.exe` WS 39 MB / private 7 MB / CPU 0,0 % (target <100 MB) |
| A3 tanpa backend saat merekam | LULUS | `rekamind-backend` = 0 proses selama 53 dtk merekam; menyala lagi setelah stop untuk unggah | |
| A4 WASAPI loopback | LULUS | CLI `record --duration 30 --stats`: kedua WAV 16 kHz mono 30,13 dtk; speaker rms 789 peak 32279; mic rms 0 (hening, tidak ada yang bicara) | Mic nyata belum divalidasi dengan suara manusia |
| A4 stats perekam | LULUS | CPU 0,10 % rata-rata, memori puncak 11,3 MB | Lebih besar dari 3,7 MB Linux, tetap kecil |
| A5 cabut/pasang headset | TIDAK DIUJI | butuh tangan | |
| A6 matikan paksa | TIDAK DIUJI | sebagian: tidak dijalankan | `recover` ada tes otomatis lulus |
| A7 pasang mesin CPU dari app | **GAGAL** | `rekamind-backend.exe engines install cpu` → `DistlibException: Unable to locate finder for 'pip._vendor.distlib'` (exit 1, 1 dtk) | **Tombol "Pasang" di app tidak bisa bekerja di Windows.** Lihat temuan 1 |
| A7 pasang CUDA via pip venv (jalur kode sama) | LULUS | 241 dtk, 2,23 GB, path terpanjang 197 (<260), `check` → `cuda_devices: 1` | Ini bukan jalur app (venv, bukan beku) |
| A7 pack + diarisasi | LULUS (pasang) | 803 dtk, 6,69 GB, path terpanjang 199 | `torch 2.14.1+cu126`, `pyannote.audio 4.0.7` |
| A7 batalkan | TIDAK DIUJI | proses beku mati dalam 12 ms saat di-kill, tapi pip gagal sebelum ada yang dibatalkan | |
| A8 transkrip + ringkasan (backend beku, pack uji, Groq) | LULUS dengan syarat | rekaman 201 dtk: 46 dtk total, 62 segmen, ringkasan ada, 1 task ("Share lagi", conf 0,9) | **Syarat:** `av` di pack saya ganti ke 16.1.0 (temuan 3). `mic.wav` rekaman ini hening sehingga pembicara "ME" tidak teruji |
| A9 kunci API tersimpan (Credential Manager) | TIDAK DIUJI | butuh UI | |
| A10 tutup jendela, tray, hotkey | SEBAGIAN | hotkey tetap jalan dengan jendela tertutup (lihat A3) | tray tidak terlihat |
| T1–T4 tab Task / pemutar / beban UI | TIDAK DIUJI | butuh UI | |
| B10 GPU terdeteksi | LULUS | `check` → `cuda_devices: 1`, ctranslate2 4.8.3 | |
| B11 large-v3, rapat 52 mnt | SEBAGIAN | transkripsi 629 segmen ± 175 dtk (RTF ≈ 0,056), VRAM puncak total 3,3 GB | Ekstraksi LLM gagal (temuan 4). Lihat tabel 3 |
| B12 bench akurasi (WER absolut) | TIDAK DIUJI | tidak ada transkrip referensi manusia (DB v1 punya 0 segmen) | Ada perbandingan relatif antar model di tabel 3 |
| B13 pemisah pembicara | **GAGAL** | job gagal di tahap `diarizing`: `No module named 'pickletools'` | Token HF terisi; model belum sempat dinilai |
| C14 Google asli | TIDAK DIUJI | tidak ada OAuth client/akun | |
| D15 S3 SeaweedFS: unggah, putar (Range), hapus | LULUS | unggah 2 objek; GET penuh 200 + `audio/wav`; Range 206 `bytes 100-199/6419340`; hapus lunak 204 (objek tetap 2); `?permanent=true` 204 → objek 0, GET 404 | |
| D15 MinIO | TIDAK DIUJI | `minio/minio` & `quay.io/minio/minio` → pull ditolak/401 | |
| D16 Postgres 16 | LULUS | migrasi otomatis saat start; dua unggahan serentak sukses; `pytest server` 155 lulus | Perlu extra `asyncpg` (`pip install -e "server[postgres]"`): bukan bug, tapi mudah terlewat |

## 3. Angka terukur GPU (GTX 1080 Ti, audio nyata 201 dtk, faster-whisper 1.2.1, bahasa id)

| Model | compute | transkripsi | RTF | VRAM puncak (total, dasar 1,2 GB) | WER relatif vs large-v3 fp32 |
|---|---|---|---|---|---|
| large-v3 | float32 (auto di Pascal) | 41,6 dtk | 0,207 | 10,75 GB (nyaris penuh 11 GB) | — |
| large-v3 | int8 | 35,1 dtk | 0,174 | 5,3 GB | 13,0 % |
| medium | float32 | 12,4 dtk | 0,062 | 4,8 GB | 41,2 % |
| small | float32 | 8,0 dtk | 0,040 | 2,6 GB | 56,7 % |

Catatan: WER di sini = beda terhadap keluaran large-v3 fp32, **bukan** akurasi terhadap kebenaran. Artinya `small` dan `medium`
menghasilkan teks sangat berbeda dari large-v3 pada rekaman rapat Indonesia ini; keputusan model tetap butuh referensi manusia (Fase 0).
Rapat 52 menit (699 MB) dengan large-v3 int8 di backend beku: transkripsi ≈ 175 dtk.

Pemasangan: engine pack CUDA 2,23 GB / 241 dtk; + diarisasi 6,69 GB / 803 dtk (jaringan rumah, cache pip hangat sebagian).

## 4. Tes otomatis di Windows

- `pytest server`: **155 lulus**, 22,8 dtk.
- `cargo test --release --no-fail-fast` di `recorder/`: api 4, cli 7, login 12, resample 6, session 10, settings 12, wav 4 lulus.
  `controller_tests`: **13 lulus, 2 gagal** (temuan 2 dan 6).
- Tes web (`vitest`/`playwright`) **tidak dijalankan**.

## 5. Yang harus diperbaiki (urut keparahan)

### 1. [KRITIS] Pemasangan mesin dari backend beku gagal di Windows
- **Gejala:** `rekamind-backend.exe engines install cpu|cuda` → `pip._vendor.distlib.DistlibException: Unable to locate finder for 'pip._vendor.distlib'`
  (jejak: `pip\_internal\req\req_install.py` → `distlib/resources.py:332 finder`). Pengguna tidak bisa memasang mesin lewat app.
- **Bukti:** `scratchpad/cpu_install.txt` (jejak penuh); backend dari installer yang baru dibangun.
- **Perkiraan penyebab:** `distlib.resources.finder()` mencari loader modul di `_finder_registry`; loader PyInstaller
  (`pyimod02_importers.PyiFrozenImporter`) tidak terdaftar. Linux lolos, Windows tidak.
- **Arah perbaikan:** daftarkan finder untuk loader beku sebelum memanggil pip (`distlib.resources.register_finder(<kelas loader>, ResourceFinder)`),
  atau jalankan pip dari interpreter terpisah. Tambahkan ke `smoke_backend.py` langkah **menjalankan** `engines install` (mis. `pip --version` / `pip install --dry-run`), bukan hanya memeriksa pip ada.

### 2. [KRITIS, kehilangan data] `Controller::discard()` bisa menghapus rekaman yang sedang berjalan di Windows
- **Gejala:** tes `a_recording_in_progress_cannot_be_discarded_or_listed_as_pending` gagal (`unwrap_err()` pada `Ok(())`, `controller_tests.rs:287`).
  `discard(live_dir)` mengembalikan Ok dan menghapus folder rekaman yang masih ditulis.
- **Penyebab:** `inside_root()` (`recorder/src/controller.rs:490`) memakai `canonicalize()` (di Windows hasilnya berawalan `\\?\`),
  sedangkan `active.session.dir()` tidak dikanonikalkan; perbandingan `a.session.dir() == dir` (baris ~483) tidak pernah sama. Hal yang sama
  kemungkinan memengaruhi pengecualian "live" di `scan_pending` (daftar "belum terunggah" bisa memuat rekaman yang sedang berjalan).
- **Arah perbaikan:** kanonikalkan kedua sisi sebelum membandingkan (atau simpan jalur kanonik di sesi). Tes sudah ada dan akan lulus.

### 3. [KRITIS] `av` 19 merusak faster-whisper 1.2.1 pada pack yang dipasang segar
- **Gejala:** transkripsi gagal: `TypeError: open() got an unexpected keyword argument 'metadata_errors'` (`faster_whisper/audio.py:46`).
- **Penyebab:** `faster-whisper` hanya mensyaratkan `av>=11`; pip memasang `av 19.0.1`, yang tidak menerima argumen itu.
  `av 16.1.0` dan `15.1.0` diuji bekerja.
- **Arah perbaikan:** pin `av<17` (atau `av==16.*`) di `enginepack.PACKAGES["asr"]` / `_bundled_pins`. Perlu periksa bahwa
  pin berlaku juga untuk jalur `--diarize` (pyannote menarik `av` sendiri).

### 4. [TINGGI] Ekstraksi LLM gagal total pada rapat panjang dengan Groq tier gratis
- **Gejala:** rapat 52 mnt: `LlmError: LLM mengembalikan 413 ... on tokens per minute (TPM): Limit 8000, Requested 10207`;
  job `failed` di tahap `extracting` (progress 80), rapat berstatus `failed`, tanpa ringkasan/task.
- **Arah perbaikan:** potong chunk sesuai batas TPM (atau bisa dikonfigurasi), tangani 413/429 dengan backoff + pembagian ulang chunk,
  dan **jangan gagalkan seluruh rapat**: tandai tahap ringkasan "belum selesai", simpan transkrip, tawarkan coba ulang.
  Transkrip 629 segmen tersimpan, jadi coba-ulang ekstraksi semestinya murah. (Kunci Groq di PC ini tier on_demand 8000 TPM untuk `openai/gpt-oss-120b`.)

### 5. [TINGGI] Diarisasi gagal di backend beku: `No module named 'pickletools'`
- **Gejala:** tahap `diarizing` gagal setelah transkripsi (±50 dtk terbuang), rapat `failed`.
- **Penyebab:** `torch` ada di `excludes` pada `rekamind-backend.spec`, sehingga PyInstaller tidak melihat modul stdlib yang hanya dipakai torch/pyannote
  dan tidak membundelnya.
- **Arah perbaikan:** tambahkan `hiddenimports` stdlib yang dibutuhkan. `pickletools` terkonfirmasi. Kandidat lain (analisis statis, belum dibuktikan):
  `cProfile`, `pstats`, `unittest.mock`, `xml.etree.ElementTree`, `mmap`, `unicodedata`, `venv`. Cara paling pasti: ulangi E2E diarisasi di backend beku
  sampai bersih. Pertimbangkan juga: bila diarisasi gagal, **lanjutkan** dengan `SingleSpeakerDiarizer` + peringatan, jangan gagalkan rapat.

### 6. [SEDANG] Tes kontrak golden JSON gagal di Windows (CRLF)
- **Gejala:** `ui_state_json_matches_the_golden_contract_file` gagal: kiri berisi `\r\n`, kanan `\n`.
- **Penyebab:** `desktop/contract/ui-state.json` di-checkout dengan CRLF (autocrlf). Bukan bug runtime.
- **Arah perbaikan:** `.gitattributes`: `desktop/contract/*.json text eol=lf` (atau normalisasi `\r\n` saat membaca di tes).

### 7. [SEDANG] Pack diarisasi menimpa `sqlalchemy`/`alembic`/`numpy` di folder pack
- **Gejala:** `pip install --target` pack memasang `sqlalchemy 2.1.4`, `alembic 1.20.0`, `numpy 2.5.4`, dll. (dari dependensi pyannote/optuna).
  Backend beku membawa versinya sendiri. Bila `enginepack.activate()` meletakkan pack di depan `sys.path`, versi pack bisa menggeser versi
  bundel (risiko ketidakcocokan). Pada uji ini backend tetap berfungsi, jadi **belum terbukti** bermasalah.
- **Arah perbaikan:** `--no-deps` untuk paket yang sudah dibundel, atau letakkan pack di belakang bundel untuk paket yang sama.

### 8. [SEDANG] Pemakaian VRAM nyaris penuh pada GPU Pascal (11 GB)
- `compute_type=auto` memilih float32 pada GTX 1080 Ti: large-v3 memakai ±9,5 GB di atas dasar (puncak total 10,75 GB), berisiko OOM bila
  GPU juga dipakai tampilan/aplikasi lain. `int8` memakai ±4 GB, lebih cepat (RTF 0,174 vs 0,207), selisih teks relatif 13 %.
- **Arah perbaikan:** untuk compute capability < 7.0 pilih `int8` (atau `int8_float32`) secara otomatis, dan tangkap OOM CUDA dengan turun ke int8/CPU.
  Evaluasi akurasi int8 vs fp32 pada referensi manusia sebelum menjadikannya default.

### 9. [RENDAH] Polling `/api/health` sangat rapat saat start
- `backend.log` memuat 1.764 permintaan `GET /api/health` dengan jarak ±7 ms (busy loop) sekitar 15 dtk pertama.
- **Arah perbaikan:** jeda 100–250 ms antar poll.

### 10. [RENDAH] `bench` tidak mengaktifkan engine pack dan melaporkan RSS 0,0 di Windows
- `python -m rekamind_server.bench` gagal `No module named 'ctranslate2'` bila mesin hanya ada di pack (tidak memanggil `enginepack.activate()`).
- `peak_rss_mb` selalu `0.0` di Windows (modul `resource` tidak ada); gunakan `psutil`/`GetProcessMemoryInfo`.

### 11. [RENDAH] Hal kecil
- Installer belum ditandatangani (diharapkan).
- Pesan NSIS bahasa Indonesia tidak diterjemahkan (`custom_language_files`).
- Di rekaman v1 yang saya uji, `speaker.wav` 48 kHz stereo diterima apa adanya oleh server (38,7 MB untuk 201 dtk); dikonversi saat diproses. Tidak ada masalah, hanya catatan penyimpanan.

## 6. Yang belum teruji dan alasannya

| Butir | Alasan |
|---|---|
| A5 headset, A6 matikan paksa interaktif, A9 Credential Manager, A10 tray, T1–T4 | butuh interaksi manusia / UI |
| Tray, notifikasi, SmartScreen, konsol berkedip | tidak bisa diamati tanpa layar |
| Mic nyata dengan suara manusia, label pembicara "ME" | `mic.wav` rekaman uji hening |
| WER absolut, akurasi diarisasi | tidak ada transkrip referensi / diarisasi gagal |
| Google asli (butir 14) | butuh OAuth client + akun |
| MinIO asli | image tidak dapat ditarik (pull ditolak) di jaringan ini |
| Tes web (vitest, Playwright) | tidak dijalankan di sesi ini |

## 7. Urutan uji ulang yang disarankan setelah perbaikan

1. Perbaiki temuan 1, 3, 5 → bangun installer di CI Windows → di PC ini: pasang, **klik "Pasang untuk NVIDIA GPU" + diarisasi dari UI**, "Uji mesin".
2. Proses rapat 52 menit (`recordings/042daa73…`) dari UI: harus selesai walau LLM tier 8000 TPM (temuan 4).
3. Ulangi `cargo test` di Windows (temuan 2 dan 6).
4. Uji manual yang tersisa: A5, A6, A9, A10, T1–T4 dan satu rapat nyata dengan suara di mic.

## 8. Status perbaikan (sesi cloud, setelah laporan di atas)

Diverifikasi di Linux (sandbox); **belum di Windows**: butir yang ditandai "uji ulang di PC".

| # | Temuan | Perbaikan | Bukti di sandbox | Uji ulang di PC |
|---|---|---|---|---|
| 1 | pip beku gagal (`distlib` finder) | `enginepack.fix_distlib_for_frozen()` mendaftarkan loader PyInstaller (`register_finder` menerima *instance*; percobaan pertama saya salah memberi tipe). Perintah baru `engines selftest` + langkah di `smoke_backend.py` | Kegagalan **direproduksi di Linux** pada biner beku (`selftest --no-fix` → `DistlibException`), lalu lulus dengan perbaikan; pasang CPU dari biner beku sukses | Klik "Pasang" dari app |
| 2 | `discard()` menghapus rekaman berjalan | `same_dir()` mengkanonikalkan kedua sisi (di `discard` dan `scan_pending`) | Tes baru dengan root berupa symlink **gagal sebelum perbaikan, lulus sesudah** | `cargo test` di Windows |
| 3 | `av` 19 merusak faster-whisper | `av>=12,<17` di pack **dan** di backend (`pyproject`), supaya pin pack = versi terbundel; `engines check` kini benar-benar men-decode audio lewat `faster_whisper.audio` | Pack terpasang segar berisi `av-16.1.0`, `check` men-decode 3200 sampel | Transkripsi dari pack segar |
| 4 | LLM 413 menggagalkan rapat | Potongan bawaan 24.000 → 12.000 karakter (`REKAMIND_LLM_CHUNK_CHARS`); 413/"too large" membelah potongan secara rekursif; 429 TPM dengan `retry-after` tetap ditunggu; bila tetap gagal **transkrip disimpan**, rapat `review` dengan pesan, dan tombol "Buat ulang ringkasan" (`POST /process?stage=extract`, tanpa transkripsi ulang) | 3 tes LLM + 3 tes degradasi (transkrip tidak ditranskripsi ulang saat coba ulang) | Rapat 52 menit dengan Groq 8000 TPM |
| 5 | `pickletools` hilang | Seluruh stdlib (termasuk submodul paket) dimasukkan ke bundel; `selftest` memeriksa modul yang dipakai torch/pyannote. Diarisasi yang gagal tidak lagi menggagalkan rapat: satu pembicara `SPEAKER_00` + catatan | `selftest` awalnya menemukan `unittest.mock` dan `xml.etree` juga hilang (submodul), sudah diperbaiki; bundel tetap 250 MB | Diarisasi dari backend beku di Windows |
| 6 | Golden JSON CRLF | `.gitattributes` (`eol=lf`) + tes menormalkan `\\r\\n` | — | `cargo test` di Windows |
| 7 | Pack menimpa pustaka bundel | `activate()` memakai `sys.path.append` (bundel menang) | tes | — |
| 8 | float32 di Pascal | `choose_compute`: float16 → int8 bila tak ada; OOM CUDA turun ke int8 lalu CPU | 6 tes (dengan model tiruan) | Pascal asli: pastikan `auto` memilih int8 (~4 GB) |
| 9 | Polling `/api/health` rapat | Penyebab sebenarnya: efek "restart" di UI yang berputar ~140×/dtk; kini maksimal sekali per 5 dtk dan health di-refetch setelah backend siap | tes | Hitung `GET /api/health` di `backend.log` |
| 10 | bench tanpa pack, RSS 0,0 | `bench` memanggil `enginepack.activate()`; probe RSS memakai argtypes yang benar dan mengembalikan `None` bila gagal | — (tak bisa diuji di Linux) | `bench` di Windows |

Temuan tambahan dari sesi ini: `OidcClient` memakai `time.monotonic()` dengan nilai awal 0, sehingga **login pertama dalam 5 menit
setelah boot gagal** ("unknown signing key"). Diperbaiki (nilai awal `-inf`) dengan tes yang gagal tanpa perbaikan.
