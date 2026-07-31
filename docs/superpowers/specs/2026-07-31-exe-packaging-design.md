# Meeting Recorder — Distributable .exe Packaging Design Spec

Date: 2026-07-31

## 1. Purpose

App ini sekarang dijalankan `python -m app.main` dari checkout source di
dalam venv — cara ini tidak bisa dibagikan ke rekan kantor non-teknis.
Spec ini merancang cara membungkusnya jadi installer Windows yang bisa
diinstall seperti app pada umumnya, sambil sejujur mungkin soal satu
ketegangan nyata dengan prinsip "harus ringan": dependency ML app ini
(torch, ctranslate2, pyannote.audio, optimum[openvino]) itu besar, dan
tidak ada cara membuat installer-nya kecil tanpa mengorbankan cakupan
device yang didukung. Trade-off yang diambil di bawah sengaja memilih
**installer besar sekali (~1-3GB) tapi satu file yang sederhana**,
dibanding beberapa installer kecil yang lebih rumit di-maintain/dibagikan.

## 2. Prinsip Utama

- **Satu installer, semua device.** CUDA + OpenVINO + CPU dalam satu paket
  — deteksi device tetap terjadi di runtime (spec hardware capability),
  bukan di waktu build/install.
- **Zero-setup untuk fungsi inti.** ffmpeg dibundle — rekan tidak perlu
  langkah manual (`winget install ffmpeg`) sebelum diarization bisa jalan.
- **Model AI TIDAK dibundle.** Ini yang menjaga installer tetap masuk akal
  ukurannya — download saat pertama dipakai adalah perilaku
  faster-whisper/pyannote yang sudah ada, tidak diubah.
- **Config & data tidak pernah di dalam folder instalasi.** Konsisten
  dengan [storage backend spec](2026-07-31-storage-backend-setup-wizard-design.md)
  — semuanya di `%LOCALAPPDATA%\MeetingRecorder\`, jadi update/uninstall
  aplikasi tidak pernah menyentuh data rekaman/database user.
- **Update itu notifikasi, bukan auto-replace.** App tidak pernah mengganti
  file dirinya sendiri saat berjalan — terlalu berisiko untuk manfaat yang
  didapat di v1.

## 3. Build Pipeline

```
pyproject.toml (versi app)
      |
      v
PyInstaller (--windowed, entry point app/main.py)
      |  bundle: python runtime + semua dependency (torch, ctranslate2,
      |  pyannote, optimum[openvino], dst) + ffmpeg.exe (statis, vendored)
      v
dist/MeetingRecorder/  (folder hasil PyInstaller)
      |
      v
Inno Setup script (.iss)
      |  Start Menu shortcut, entry Programs & Features, uninstaller
      v
MeetingRecorderSetup-<version>.exe   <- yang dibagikan ke rekan
```

PyInstaller dipilih dibanding Nuitka: dependency stack app ini (terutama
torch dan ctranslate2) banyak pakai dynamic import/native extension yang
sudah punya banyak resep/precedent kerja dengan PyInstaller, sementara
kompilasi Nuitka lebih rawan patah untuk pola seperti ini.

## 4. Bundling ffmpeg

Binary statis `ffmpeg.exe` (bukan paket dev lengkap) disertakan di dalam
folder instalasi (`<install_dir>\ffmpeg\ffmpeg.exe`). Satu baris tambahan
di awal `app/main.py::main()`:

```python
_bundled_ffmpeg_dir = Path(sys.executable).parent / "ffmpeg"
if _bundled_ffmpeg_dir.exists():
    os.environ["PATH"] = f"{_bundled_ffmpeg_dir}{os.pathsep}{os.environ['PATH']}"
```

...dijalankan SEBELUM `check_ffmpeg_available()` — fungsi itu sendiri
(`shutil.which("ffmpeg")`) tidak berubah sama sekali, cuma sekarang selalu
menemukan salinan yang dibundle tanpa rekan perlu install apa pun. Mode
dev (jalan dari source, tidak ada folder `ffmpeg/` di sebelah executable)
tidak terpengaruh — tetap mengandalkan ffmpeg dari PATH sistem seperti
sekarang.

## 5. Versi & Update Check (`app/update_check.py`, baru)

```python
def check_for_update(current_version: str, releases_api_url: str) -> str | None:
    """Return versi baru (mis. "0.2.0") kalau ada yang lebih baru dari
    current_version, None kalau sudah versi terbaru atau gagal cek
    (network error tidak boleh mengganggu startup)."""
```

Dipanggil di background thread saat `main()` startup (tidak memblokir
window muncul), membandingkan `pyproject.toml`'s `version` dengan tag
rilis terbaru dari Releases API (format response GitHub dan GitLab cukup
mirip — `releases_api_url` dibuat configurable, bukan di-hardcode ke satu
host, jadi tidak terikat keputusan GitHub vs GitLab-nya UGM sekarang).
Hasil dikirim ke `MainWindow` lewat mekanisme sama seperti
`live_warning_label` yang sudah ada (`root.after(0, ...)`) — notifikasi
non-blocking "Update tersedia: v0.2.0" dengan link, bukan dialog yang
menghalangi pemakaian. Gagal cek (offline, API down) — diam saja, tidak
ada pesan error yang mengganggu.

## 6. Yang TIDAK Dibundle

- **Model AI** (whisper, pyannote, silero-vad) — download saat pertama
  dipakai, sama seperti sekarang. Rekan butuh internet + (opsional)
  `HF_TOKEN` di wizard untuk model pyannote yang gated — kalau dilewati,
  diarization tetap best-effort nonaktif sesuai
  [hardware capability spec](2026-07-31-hardware-capability-check-design.md).
- **CUDA toolkit terpisah** — tidak relevan, ctranslate2/torch CUDA wheel
  yang dibundle PyInstaller sudah membawa runtime CUDA yang dibutuhkan.

## 7. Testing

- Tidak ada unit test baru untuk proses build itu sendiri (di luar
  cakupan pytest — ini pipeline build, bukan kode aplikasi).
- `tests/test_update_check.py` (baru): `check_for_update()` dengan HTTP
  response di-mock — versi lebih baru terdeteksi, versi sama/lebih lama
  mengembalikan `None`, network error tertangkap jadi `None` (tidak raise).
- Verifikasi manual (bukan otomatis, dicatat di sini supaya tidak
  terlupa): install hasil Inno Setup di mesin bersih (bukan mesin dev),
  konfirmasi wizard first-run muncul, ffmpeg bundled terdeteksi, dan app
  berjalan tanpa Python/venv terinstall sama sekali di mesin itu.

## 8. Di Luar Cakupan (v1)

- Full auto-update (download + install otomatis, ganti exe yang sedang
  berjalan) — dianggap terlalu berisiko untuk manfaat yang didapat
  dibanding notifikasi + install manual.
- Code signing — installer akan memicu peringatan Windows SmartScreen
  (unsigned publisher). Beli sertifikat code-signing adalah keputusan
  biaya/organisasi di luar cakupan desain ini, bukan sesuatu yang bisa
  diputuskan lewat spec.
- Installer terpisah per-device (CPU-only vs CUDA) — sudah diputuskan
  satu installer universal (§2).
- Auto-detect & pilih host Releases API (GitHub vs GitLab UGM) secara
  otomatis — `releases_api_url` dikonfigurasi manual sekali saat build,
  bukan dipilih runtime.
