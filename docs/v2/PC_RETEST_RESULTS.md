# Hasil uji ulang di PC (Windows 11 + GTX 1080 Ti)

Tanggal: 2026-10-15. Commit uji: `dda66df` (di atas `b2374c1`) + perbaikan `install()` di sesi ini. GPU: GTX 1080 Ti 11 GB.
Status: jalur utama lulus; butir yang butuh tangan/telinga pengguna (R3, R10, A5-A10, M1, T1-T4) BELUM diuji.
Lihat "Laporan akhir" di bawah untuk ringkasan wajib.

## Laporan akhir

### (1) Temuan lama #1-#10

| # | Temuan | Status | Bukti |
|---|---|---|---|
| 1 | pip beku gagal (distlib) | TERATASI, setelah perbaikan tambahan | Klaim awal tidak menutup `install()` (hanya `selftest`); gagal di PC, diperbaiki, lalu pasang CUDA+diarisasi lewat CLI dan UI sukses |
| 2 | `discard()` menghapus rekaman berjalan | TERATASI di tes otomatis; uji manual R10 BELUM | `cargo test` semua lulus (controller 15) |
| 3 | `av` 19 merusak faster-whisper | TERATASI | `av-16.1.0` di pack; transkripsi dari pack segar berjalan |
| 4 | LLM gagal pada rapat panjang | TERATASI sebagian | Rapat 85 mnt: 9x 429 pulih sendiri, job `done`, 9 task. Tombol "Buat ulang ringkasan" tidak terpicu, jadi belum teruji |
| 5 | `pickletools` hilang, diarisasi gagal | TERATASI | 4 pembicara dari backend beku, `missing_stdlib: []` |
| 6 | Golden JSON CRLF | TERATASI | `cargo test` lulus, `eol=lf` |
| 7 | Pack menimpa pustaka bundel | TIDAK DIVERIFIKASI langsung | Aplikasi berjalan normal setelah pack terpasang; tidak ada pemeriksaan versi `sqlalchemy`/`alembic`/`numpy` |
| 8 | VRAM nyaris penuh di Pascal | TERATASI | `auto` -> `cuda`/`int8`; 3,3-4,2 GB, puncak 5,3 GB (diarisasi); dulu 10,75 GB |
| 9 | Polling `/api/health` rapat | TERATASI | satu per 15 dtk (target: puluhan dalam 20 dtk pertama) |
| 10 | `bench` tanpa pack, RSS 0 | TERATASI | `peak_rss_mb` 4124, memakai pack otomatis |

### (2) Temuan baru (urut keparahan)

1. [TINGGI, sudah diperbaiki] `install()` tidak memanggil `fix_distlib_for_frozen()`; `selftest` melapor ok padahal pemasangan nyata gagal. Uji `selftest` memberi rasa aman palsu.
2. [SEDANG] Backend dijalankan ulang sendiri berkali-kali tanpa log shutdown/galat (08:31, 08:46, 08:48, 09:25, 09:36) sementara UI tidak restart. Penyebab belum diketahui; kemungkinan berkaitan dengan aksi di Pengaturan, belum diverifikasi. Bisa memutus pekerjaan yang sedang berjalan bila terjadi saat pemrosesan.
3. [SEDANG] Unduhan model pertama (2,9 GB, ±6,5 mnt) tanpa progres di log/UI; terlihat seperti hang. Cache model aplikasi (`backend\models`) terpisah dari `~\.cache\huggingface`.
4. [SEDANG] Peringatan `unauthenticated requests to the HF Hub`: token HF tidak sampai ke pemuatan model Whisper walau diarisasi berhasil.
5. [RENDAH] Rekaman tanpa ucapan tetap memanggil Groq untuk ringkasan kosong; tampilkan "tidak ada ucapan terdeteksi".
6. [RENDAH] CLI `engines` memakai pack di `~\.rekamind\engine-pack`, UI memakai folder data aplikasi; dua lokasi berbeda dan folder sisa `id.rekamind.desktop-test`.
7. [RENDAH] `build_desktop.py` gagal dengan pesan samar bila `cargo` tidak di PATH; Playwright gagal bila `python` venv tidak aktif.

### (3) Tidak bisa diuji

R3 (Batalkan), R7 (OOM, opsional), R10 (rekaman berjalan tidak bisa dihapus), R12 (opsional, tanpa server Google),
A5 (headset), A6 (mati paksa), A9 (kunci tersimpan setelah keluar), A10 (tray), M1 (mikrofon nyata),
T1-T4 (tab Task), R5 dengan `mic.wav` (pembicara ME), kualitas hasil (akurasi teks/speaker/task).
Butuh tangan, telinga, atau layar pengguna; tidak ada di sesi otomatis.

### (4) Berkas untuk pengembang

`backend.log`: `%LOCALAPPDATA%\id.rekamind.desktop\backend\logs\backend.log`. Keluaran `selftest`/`--no-fix` dan hasil
`cargo test` ada di bagian Tabel di bawah. Kegagalan pemasangan asli: traceback `DistlibException` dari `wheel.py:33`
(tercantum di bagian R2). Tidak ada screenshot galat.

## Tabel

| Butir | Status | Bukti | Catatan |
|---|---|---|---|
| Langkah 0.1 av 16.x | LULUS | `av 16.1.0` | |
| Langkah 0.2 build | LULUS | `build_desktop.py` 4,1 mnt; installer `Rekamind_0.0.1_x64-setup.exe` 67,84 MiB | Percobaan pertama gagal: `cargo` tidak ada di PATH sesi (ada di `~\.cargo\bin`). Bukan bug kode. |
| Langkah 0.3 smoke | LULUS | "Smoke test lulus."; baris terakhir `pip can locate its own resources ... {'ok': True, 'missing_stdlib': []}` | Jumlah baris ok yang terlihat 13 dari keluaran 25 baris terakhir; belum dihitung penuh terhadap target 14. |
| R1 selftest | LULUS | `{"ok": true, "frozen": true, "missing_stdlib": []}` | Dijalankan pada backend hasil build (`resources\backend`), bukan pada instalasi terpasang. |
| R1 `--no-fix` | LULUS (gagal sesuai harapan) | `DistlibException: Unable to locate finder for 'pip._vendor.distlib'` | Membuktikan perbaikan pip-beku memang yang bekerja. |
| R9 cargo test | LULUS | api 4, cli 7, controller 15, login 12, resample 6, session 10, settings 12, wav 4, semuanya 0 gagal | `git ls-files --eol`: `i/lf w/crlf attr/text eol=lf`. |
| R13 pytest server | LULUS | `170 passed in 22.71s` | |
| W1 vitest | LULUS | 7 berkas, 61 tes | |
| W1 playwright | LULUS | 22 lulus (53 dtk) | Harus dijalankan dengan venv aktif; tanpa itu `webServer` memakai stub `python.exe` WindowsApps. |

## Pemasangan bersih (Langkah 4) dan R1 pada instalasi terpasang

Uninstall lama, hapus `engine-pack` (`recordings\` utuh), pasang installer baru: tidak ada proses yatim.
`...\Rekamind\backend\rekamind-backend.exe engines selftest` -> `ok: true`; `--no-fix` -> `DistlibException` (LULUS).

## R2 GAGAL (lewat CLI `engines install --diarize cuda`)

Pemasangan berhenti dalam < 1 menit, exit 1, dengan galat yang sama persis dengan temuan lama:
`pip._vendor.distlib.DistlibException: Unable to locate finder for 'pip._vendor.distlib'`
(`pip\_internal\operations\install\wheel.py:33` -> `distlib\scripts.py:66` -> `distlib\resources.py:332 finder`).

Penyebab (diverifikasi dengan membaca kode, kode tidak diubah): `fix_distlib_for_frozen()` hanya dipanggil dari
`selftest()` (`enginepack.py:168`). `install()` (`enginepack.py:197`) langsung memanggil `pip_main` tanpa menerapkan
perbaikan itu, jadi `selftest` ok tetapi pemasangan nyata tetap gagal. Uji `test_selftest_runs_the_distlib...`
tidak mencakup `install()`. Belum diverifikasi: apakah tombol UI memakai jalur sidecar yang sama (kemungkinan besar ya).

### Perbaikan yang diterapkan pada sesi ini

`install()` kini memanggil `fix_distlib_for_frozen()` sebelum pip; ditambah uji
`test_install_applies_the_frozen_distlib_fix_before_running_pip`. pytest server: 171 lulus. Build ulang + smoke lulus.

### R2 setelah perbaikan (CLI `engines install --diarize cuda`, backend terpasang)

| Butir | Status | Bukti |
|---|---|---|
| R2 pasang NVIDIA + diarisasi | LULUS (CLI) | exit 0, 16,7 menit, pack 6,73 GB |
| `engines check` | LULUS | `ok: true, cuda_devices: 1, ctranslate2 4.8.3, faster_whisper 1.2.1` |
| versi av di pack | LULUS | `av-16.1.0.dist-info` |
| path terpanjang | LULUS | 162 karakter (< 260), di `torch-...dist-info\licenses\...` |
| paket diarisasi | ada | pyannote_audio 4.0.7, torch 2.14.1+cu126 |
| R11 bench | LULUS | `large-v3`, `auto` -> `cuda`/`int8`, `peak_rss_mb` 4124, realtime_factor 0,019 |
| VRAM puncak (R4, sebagian) | LULUS | 3076 MiB total GPU (dulu 10,75 GB) pada rekaman 60 dtk |

Catatan: CLI memakai pack di `C:\Users\aji\.rekamind\engine-pack` (bukan folder data aplikasi). Tombol UI belum dicoba,
jadi progres, batalkan (R3) dan lokasi pack yang dipakai app belum terverifikasi. Ada juga folder sisa
`id.rekamind.desktop-test\backend\engine-pack` dari uji sebelumnya.

## Uji lewat aplikasi terpasang (pack dari UI, kunci Groq + token HF dari `.env`)

| Butir | Status | Bukti |
|---|---|---|
| R2 pasang lewat UI | LULUS | pack 6,73 GB di `id.rekamind.desktop\backend\engine-pack`, `installed.json` = cuda + diarize |
| R4 pemilihan model | LULUS | log `loading whisper large-v3 on cuda (int8)` |
| R4 VRAM | LULUS | 3,25-3,8 GB saat transkripsi (dulu 10,75 GB); puncak 5,3 GB saat diarisasi + merging |
| R5 diarisasi (backend beku) | LULUS | 4 pembicara (SPEAKER_00..03), tahap `diarizing` selesai tanpa galat |
| R6 batas TPM Groq | LULUS | 9 respons 429, semuanya pulih (200 OK setelah menunggu 8-56 dtk); job `done`, 9 task, ringkasan terisi |
| R8 health polling | LULUS | `GET /api/health` tiap 15 dtk |
| Rapat 85 mnt (hanya speaker.wav) | LULUS | 1173 segmen, 802 dtk total: transkripsi ±6,8 mnt, diarisasi ±2,5 mnt, ekstraksi ±4 mnt |
| Rekaman tanpa ucapan | LULUS | status `review`, 0 segmen, tanpa galat |

Bench `large-v3` 9 rapat nyata (28-94 mnt), RTF 0,04-0,12, semua selesai. VRAM bersih 3,7-4,2 GB.

### Temuan baru dari uji aplikasi
1. Unduhan model pertama (2,9 GB, ±6,5 mnt) tanpa progres di log/UI; terlihat seperti hang. Cache model aplikasi (`backend\models`) terpisah dari `~\.cache\huggingface`, jadi diunduh ulang.
2. Peringatan `unauthenticated requests to the HF Hub`: token HF belum diteruskan ke pemuatan model Whisper, padahal diarisasi (yang butuh token) berhasil. Perlu dicek jalur env `HF_TOKEN`.
3. Backend dijalankan ulang oleh aplikasi 3x (08:31, 08:46, 08:48) tanpa galat; kemungkinan sengaja setelah pemasangan/penyimpanan kunci, belum diverifikasi di kode.
4. Rekaman tanpa ucapan tetap memanggil Groq untuk ringkasan kosong; sebaiknya tampil "tidak ada ucapan terdeteksi".
5. Peserta tidak mendapat nama (`name` kosong); pembicara "ME" tidak diuji karena hanya `speaker.wav` yang diunggah.

## Belum diuji

R3 (batalkan), R5 dengan mic.wav (pembicara ME), R2 via UI (progres terlihat tidak sempat dicatat) (progres), R3 (batalkan), R4 (transkripsi: satu-satunya rekaman di mesin ini hanya ±60 dtk dan bukan ucapan,
`mic.wav` peak 6, `speaker.wav` 0 segmen; data 201 dtk dan 52 mnt tidak ada), R5, R6, R7 (opsional), R8, R10,
R12 (opsional), A5, A6, A9, A10, M1, T1-T4.

## Temuan baru

0. (BLOKER, SUDAH DIPERBAIKI di sesi ini, belum di-commit) Temuan lama #1 masih ada di jalur `install`: perbaikan distlib hanya diterapkan oleh `selftest`, bukan `install`. Lihat bagian R2.
1. (Ringan, lingkungan) Skrip build dan Playwright bergantung pada PATH sesi: `cargo` dan `python` venv harus aktif. Pertimbangkan pesan galat yang lebih jelas di `scripts/build_desktop.py`.
