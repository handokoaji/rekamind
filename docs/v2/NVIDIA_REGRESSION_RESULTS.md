# Hasil uji regresi CPU + NVIDIA (GTX 1080 Ti, Windows 11)

Build teruji: `0.4.0-beta.1`, build `fd575dc` (artifact CI `rekamind-installer-windows-latest`, dipasang `/S`), pip beku 26.2, Python 3.13.
Driver NVIDIA 582.66, VRAM 11 GB. Tanpa variabel lingkungan pip/proxy. Token HF/Groq ada di `.env` (tidak dicatat di sini).

**Cakupan:** hanya yang bisa dijalankan tanpa GUI (CLI `rekamind-backend.exe engines ...` dan pengukuran terminal).
Butir yang butuh klik UI / rekaman / idle ditandai TIDAK BISA DIUJI.

## Tabel

| # | Status | Bukti singkat |
|---|---|---|
| N1 | **GAGAL (versi pyannote, via CLI `install cuda --diarize`)** | Macet 0,01-0,2 MB/s pada `nvidia_cuda_nvrtc_cu12` (76 MB), dua kali (197 dtk lalu dibatalkan). Tanpa pyannote: LULUS (32 dtk, dari cache). UI tidak diuji. |
| N2 | LULUS (pasang bersih tanpa pyannote) | `check`: `{"ok": true, "cuda_devices": 1, "ctranslate2": "4.8.3", "faster_whisper": "1.2.1"}`; `status`: `kind: cuda`, `asr: true`, `gpus: [nvidia GTX 1080 Ti]`. |
| N3 | TIDAK BISA DIUJI | Tidak ada rekaman Indonesia >= 3 menit; transkripsi/VRAM belum diukur. |
| N4 | LULUS sebagai pembanding | Blok Diagnostik identik, dan CLI sama lambatnya dengan jalur yang sama (lihat jawaban di bawah). |
| N5 | LULUS (pembanding) | pip 25.0.1 biasa: wheel nvrtc 76 MB dalam 16 dtk. `curl` ke `files.pythonhosted.org`: 5,7 MB/s. `curl` ke `pypi.nvidia.com`: 28 KB/s. |
| N6 | TIDAK DIUJI | Satu jam saja. |
| N7 | SEBAGIAN | Membunuh proses install (`taskkill /T`): tidak ada proses `rekamind-backend` tersisa, tidak ada `*.part`. Resume tidak diukur (macet sebelum 20%). |
| N8 | LULUS | `install cpu` exit 0, 11 dtk; `status`: `kind: cpu`; `check ok: true`. Transkripsi CPU tidak diuji. |
| N9 | LULUS (pasang) | `install cuda` exit 0, 23 dtk; `kind: cuda`; `check ok: true`, `cuda_devices: 1`. Transkripsi di cuda tidak diuji. |
| N10 | LULUS | `engines status` 0,25-0,74 dtk; `gpus.json` ada. |
| N11 | TIDAK BISA DIUJI | Butuh GUI. |
| N12 | TIDAK BISA DIUJI | Butuh GUI. |
| N13 | TIDAK BISA DIUJI | Butuh GUI. |

Diagnostik (N1/N4, contoh): `pip 26.2, Python 3.13`, `pypi.org DNS 0.01 dtk TLS 0.12 dtk`, `files.pythonhosted.org DNS 0.12 / TLS 0.26`,
`download.pytorch.org DNS 0.26 / TLS 0.04` (varian `--diarize`).

## Mengapa lambat dari .exe? (fakta)

1. Jaringan sehat: `files.pythonhosted.org` 5,7 MB/s, pip biasa 16 dtk untuk 76 MB.
2. Pemasangan tanpa pyannote hanya memakai PyPI (wheel cuDNN/cuBLAS dari `files.pythonhosted.org`) dan lancar.
3. Dengan `--diarize` pip menambah `--extra-index-url https://download.pytorch.org/whl/cu126`. Indeks itu mencantumkan `nvidia-cuda-nvrtc-cu12==12.9.86`
   dengan tautan ke **`https://pypi.nvidia.com/...`**. pip memilih tautan itu, dan host itu hanya ±28 KB/s dari jaringan ini
   (`curl`: 1,7 MB dalam 60 dtk). Laju pip menurun 0,23 -> 0,01 MB/s di tiap percobaan.
4. Hasil terminal "lancar" kemungkinan karena diuji tanpa pyannote atau dari cache. Itu hipotesis, bukan fakta terukur.

Dugaan penyebab [Medium]: host `pypi.nvidia.com` (CDN) lambat di jaringan ini, dan `--extra-index-url` PyTorch membuat pip lebih memilihnya.
Belum dibuktikan bahwa itu lambat di jaringan lain.

## Temuan (urut keparahan)

1. **[Tinggi] Pemasangan NVIDIA + pyannote macet** karena wheel `nvidia-*` diambil dari `pypi.nvidia.com` lewat indeks PyTorch.
   Peringatan "Tidak ada kemajuan" tidak muncul karena byte masih mengalir pelan. Ide (tidak diterapkan): pasang paket `nvidia-*`
   dari PyPI saja (langkah terpisah tanpa extra index) sebelum torch, atau tetapkan `--index-url` PyPI dan `-f`/`--extra-index-url` hanya untuk `torch*`.
2. **[Tinggi, belum direproduksi] `engines check` GAGAL pada pack lama** (6,9 GB, `kind: cuda`, diarize: true):
   `AttributeError: module 'ctranslate2' has no attribute 'StorageView'` sementara `engines status` melapor `asr: true`.
   Pack sudah saya hapus sebelum penyebabnya diselidiki, jadi tidak bisa direproduksi. Pack bersih tanpa pyannote lulus.
   Perlu diuji ulang setelah `--diarize` bisa selesai. `status` tidak memverifikasi impor ctranslate2.
3. **[Sedang] Peringatan macet** (60 dtk tanpa kemajuan) tidak menangkap unduhan yang menetes (<0,05 MB/s). Pertimbangkan ambang kecepatan.
4. **[Rendah] Uji tergantung cache pip**: N8/N9 dan install tanpa pyannote berasal dari cache, bukan ukuran unduhan nyata.

## Keputusan

**NO-GO (sementara).** N1 (pyannote) GAGAL dan N3 belum terukur. Jalur CPU/NVIDIA tanpa pyannote tidak rusak (N2, N8, N9, N10 LULUS).
Yang perlu dilakukan sebelum merge: (a) perbaiki sumber `nvidia-*` untuk `--diarize`, (b) ulangi N1 dan reproduksi temuan 2,
(c) jalankan N3 dan butir GUI (N7, N11-N13) secara manual.
