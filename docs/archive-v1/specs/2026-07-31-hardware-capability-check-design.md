# Meeting Recorder — GPU/CPU Hardware Capability Check Design Spec

Date: 2026-07-31

## 1. Purpose

`app/asr/detect.py::detect_backend()` sudah punya cascade
`cuda -> openvino (GPU/NPU) -> cpu`, yang seharusnya sudah otomatis
mencakup perangkat seperti Intel Ultra 7 155H (Meteor Lake, Arc iGPU + NPU)
lewat jalur `openvino` tanpa perubahan apa pun — GPU tetap prioritas utama,
CPU tetap fallback terakhir, sesuai yang sudah diminta.

Celah yang ada: cabang `cpu` di akhir cascade tidak pernah divalidasi, cuma
diasumsikan selalu bisa jalan. Kalau `ctranslate2` (mesin di balik
faster-whisper) tidak bisa jalan sama sekali di perangkat itu — instalasi
rusak, arsitektur CPU tidak didukung wheel yang terpasang, dependency
native hilang — app tetap nekat lanjut, baru gagal jauh lebih belakang saat
model benar-benar dimuat (di dalam `WhisperModel(...)`), dengan pesan error
yang tidak jelas asalnya dan setelah window sudah terbuka.

Spec ini menutup celah itu: validasi CPU secara eksplisit, dan kalau
benar-benar tidak ada backend yang sanggup (GPU maupun CPU), app menolak
jalan sama sekali dengan pesan jelas — bukan buka window dulu baru crash.

## 2. Prinsip Utama

- **Tidak menambah logika deteksi GPU baru.** `_cuda_available()` dan
  `_openvino_gpu_or_npu_available()` yang sudah ada tidak berubah.
- **Hanya ASR (transkrip) yang jadi syarat keras.** Itu fungsi inti app.
  Diarization/ringkasan tetap *best-effort* seperti sekarang (pola yang
  sama dengan penanganan ffmpeg hilang yang sudah ada) — device yang cuma
  sanggup transkrip tanpa speaker labels tetap boleh pakai app ini.
- **Gagal cepat, sebelum window terbuka.** Kalau memang tidak sanggup,
  app keluar dengan pesan jelas di awal, bukan setelah user sempat
  berinteraksi dengan UI.

## 3. Perubahan `app/asr/detect.py`

```python
class UnsupportedHardwareError(RuntimeError):
    """Tidak ada backend ASR (GPU maupun CPU) yang bisa jalan di perangkat ini."""


def _ctranslate2_importable() -> bool:
    try:
        import ctranslate2  # noqa: F401
        return True
    except ImportError:
        return False


def _cuda_available() -> bool:
    if not _ctranslate2_importable():
        return False
    import ctranslate2
    return ctranslate2.get_cuda_device_count() > 0


def detect_backend(override: str = "") -> str:
    if override:
        return override
    if _cuda_available():
        return "cuda"
    if _openvino_gpu_or_npu_available():
        return "openvino"
    if _ctranslate2_importable():
        return "cpu"
    raise UnsupportedHardwareError(
        "Perangkat ini tidak mendukung transkripsi audio (GPU tidak "
        "terdeteksi dan CPU tidak sanggup menjalankan mesin ASR). "
        "Aplikasi tidak bisa dijalankan di perangkat ini."
    )
```

`_ctranslate2_importable()` dipisah dari `_cuda_available()` supaya
"ctranslate2 tidak bisa diimpor sama sekali" (benar-benar tidak sanggup)
dan "ctranslate2 jalan tapi 0 CUDA device" (lanjut ke openvino/cpu) tidak
lagi tercampur jadi satu `False` yang sama seperti sekarang.

## 4. Perubahan `app/main.py`

```python
def main() -> None:
    configure_logging()
    settings = get_settings()
    check_ffmpeg_available()
    ...
    try:
        backend_name = detect_backend(settings.asr_backend_override)
    except UnsupportedHardwareError as exc:
        _fatal_error(str(exc))
        return
    ...
    # window Tk baru dibuat setelah titik ini
```

`_fatal_error(message)`: `root = tk.Tk(); root.withdraw()`, lalu
`messagebox.showerror("Meeting Recorder", message)`, lalu `sys.exit(1)`.
Tidak perlu library baru — `tkinter.messagebox` sudah jadi dependency app
ini. Dipanggil SEBELUM `MainWindow`/`RecorderController` dibuat sama
sekali, jadi tidak ada state app yang sempat terbentuk.

## 5. Catatan Verifikasi (Intel Ultra 7 155H)

Logika di atas TIDAK diuji langsung di hardware Intel Ultra 7 155H selama
sesi desain ini (tidak tersedia) — kesimpulan "harus otomatis lewat jalur
openvino" berdasar baca kode `_openvino_gpu_or_npu_available()` (mendeteksi
device yang namanya diawali `GPU`/`NPU` dari `openvino.Core().available_devices`,
dan Meteor Lake punya keduanya). Ini asumsi yang masuk akal, bukan fakta
terverifikasi — perlu dikonfirmasi jalan sungguhan di perangkat itu saat
implementasi, bukan cuma lewat unit test yang di-mock.

## 6. Testing

- `tests/asr/test_detect.py` (baru): `detect_backend()` dengan
  `ctranslate2`/`openvino` di-monkeypatch:
  - CUDA tersedia → `"cuda"` (tidak berubah dari sekarang).
  - CUDA tidak ada, openvino GPU/NPU ada → `"openvino"` (tidak berubah).
  - Keduanya tidak ada, `ctranslate2` importable → `"cpu"` (tidak berubah).
  - Keduanya tidak ada, `ctranslate2` **tidak** importable →
    `UnsupportedHardwareError` (baru).
  - `override` diisi → dipakai apa adanya, tidak pernah raise (tidak berubah).
- `tests/test_main.py`: `main()` dengan `detect_backend` di-monkeypatch
  raise `UnsupportedHardwareError` → `messagebox.showerror` terpanggil,
  `MainWindow`/`RecorderController` TIDAK pernah dibuat, `sys.exit`
  terpanggil dengan kode bukan-nol.

## 7. Di Luar Cakupan (v1)

- Benchmark performa CPU (mis. estimasi kecepatan transkrip berdasarkan
  jumlah core/instruksi CPU) — hanya soal "bisa jalan atau tidak", bukan
  "seberapa cepat".
- Syarat keras untuk diarization/pyannote/torch (tetap best-effort, §2).
- Deteksi kapabilitas RAM/disk minimum.
