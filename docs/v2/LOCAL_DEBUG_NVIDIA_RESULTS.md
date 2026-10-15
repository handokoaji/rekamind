# Hasil debug lokal NVIDIA (GTX 1080 Ti)

Mesin: GTX 1080 Ti 11 GB, driver 582.66, Windows 11 build 26300, branch `feat/amd-vulkan` @ 57fc09a. Aplikasi: installer terpasang
(`%LOCALAPPDATA%\Rekamind`), perekam diuji dari kode (`recorder/`, rustc 1.99.0 MSVC).

## Akar masalah (terbukti) [High confidence]
`wasapi::AudioCaptureClient::read_from_device_to_deque` hanya membaca **satu paket (~10 ms)** per panggilan
(`wasapi-0.22.0/src/api.rs:1777`, satu `GetBuffer`). `recorder/src/backend/wasapi_backend.rs::run_stream` memanggilnya sekali per
poll 100 ms, jadi ~10% audio tersimpan dan `Pacer` menambal sisanya dengan nol (siklus ~200 ms: 180 ms nol + 20 ms sinyal).
Audio patah-patah itu dibuang seluruhnya oleh VAD: `faster_whisper: VAD filter removed 10:13.685 of audio` (mic dan speaker),
sehingga transkrip kosong dan muncul "Tidak ada ucapan terdeteksi".

## Bukti
Rekaman 10 menit asli (sebelum fix), `backend/recordings/4679ab…`:
| berkas | puncak | zero-run >20 ms | detik nol | median run |
|---|---|---|---|---|
| speaker.wav | 32768 | 2843 | 556,9 dari 613,7 | 181 ms |
| mic.wav | 6 | 3054 | 553,7 | 181 ms |

A/B 30 detik, TTS ke speaker, skenario identik (`--no-mic`):
| | lama | baru |
|---|---|---|
| zero-run >20 ms | 140 | 2 |
| detik nol | 27,36 | 1,99 (jeda 2 dtk sebelum TTS) |
| frame 30 ms RMS>100 | 17,5% | 71,8% |

## Perubahan
- `fc5bd12` fix(recorder): kuras semua paket per poll (`drain_packets`, batas 1000 paket/poll) + 5 tes unit tanpa perangkat keras.
- `cargo test` lulus (semua suite), `cargo clippy --all-targets -- -D warnings` bersih.

## Status butir
| butir | status |
|---|---|
| Masalah 2: speaker.wav patah-patah | **LULUS** di app terpasang, rekaman nyata 243,6 dtk: 3 run nol (3,18 dtk, 1,3%), frame ber-energi 98,4% (lama: 22,3%) |
| Masalah 1: transkrip kosong | **LULUS** di app terpasang: `large-v3` di `cuda`, VAD membuang 2,4 dari 243,6 dtk speaker (lama: 100%), 72 segmen Indonesia yang benar |
| mic.wav level ~0 (puncak 5/32768, RMS 0,5 pada rekaman 243 dtk) | **TERBUKA**, bukan bug perekam: tidak patah-patah (2 run nol), VAD membuang 100% mik, 0 segmen mik. Default capture = "Headset Microphone (MH752)"; cek mute/gain/perangkat default |
| A1-A3 pemasangan NVIDIA, cache dingin | TIDAK DIUJI di sesi ini |
| B2 mesin vs perekam (WAV bersih) | TIDAK DIUJI (mesin NVIDIA memuat `large-v3` di `cuda` per log, tidak crash) |
| `pytest server`, `ruff check` | TIDAK DIJALANKAN (server tidak diubah); wajib sebelum push |
| Diagnostik flag WASAPI (SILENT/DISCONTINUITY) | TIDAK DIBUAT; `SILENT` belum ditangani, bukan akar masalah ini |

## Belum terselesaikan
1. Pasang ulang aplikasi dari build yang memuat `fc5bd12` (perekam terpasang masih kode lama, tertanam di `rekamind.exe`), rekam 10 menit, proses.
2. Mic: rekam sambil berbicara dan ukur ulang.
3. Dugaan, belum dibuktikan: clipping puncak 32768 di speaker.wav lama mungkin dari paket berflag SILENT; ukur setelah fix.

## Temuan tambahan selama uji di app terpasang
- **Kesalahan build lokal (bukan bug repo):** installer pertama dibangun dengan venv Python 3.14, padahal engine-pack berisi modul `cp313` dan CI
  rilis memakai 3.13. Akibatnya `ctranslate2._ext` tak termuat; `except ImportError` di ctranslate2 menelan "No module named" dan
  pemrosesan gagal dengan `module 'ctranslate2' has no attribute 'get_cuda_device_count'`. Diperbaiki dengan membangun ulang di Python 3.13
  (`engines check`: `ok: true`, `cuda_devices: 1`). Jalankan `build_desktop.py` hanya dari Python 3.13.
- **Perilaku desain, bukan bug:** saat merekam, backend lokal sengaja dimatikan (`controller.rs:282`) dan tidak boleh dinyalakan
  (`controller.rs:228`), sehingga UI menampilkan "Tidak dapat terhubung ke server" selama rekaman. Pesannya menyesatkan; perlu teks UX terpisah.
- Belum dijalankan: `pytest server`, `ruff check`, rekaman 10 menit; instalasi A1-A3 (cache dingin pypi.nvidia.com) tidak diuji.
