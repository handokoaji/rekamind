# Meeting Recorder — MinIO File & Metadata Sync Design Spec

Date: 2026-07-31

## 1. Purpose

Default penyimpanan tetap 100% lokal (lihat
[storage backend spec](2026-07-31-storage-backend-setup-wizard-design.md)).
Spec ini menambahkan sinkronisasi **opsional** lewat MinIO supaya meeting
dari berbagai perangkat/orang bisa saling terlihat dan diakses — dipicu
manual lewat satu tombol, bukan otomatis di background.

Tantangan utama BUKAN nama file bentrok (folder meeting sudah pakai
`uuid.uuid4().hex`, jadi unik) — tapi **metadata**. Kalau tiap orang pakai
SQLite lokal masing-masing (skenario utama distribusi `.exe`), database
mereka tidak saling tahu meeting apa saja yang ada di device lain. MinIO di
sini menyimpan bukan cuma file audio/docx, tapi juga manifest metadata
supaya proses **pull** bisa merekonstruksi baris meeting di database lokal
device lain.

## 2. Prinsip Utama

- **Manual, dua arah, satu tombol.** "Sync Sekarang" melakukan push (upload
  meeting milik device ini yang belum ter-upload) dan pull (tarik metadata
  meeting dari device lain yang belum diketahui) dalam satu aksi. Tidak ada
  sync otomatis/background.
- **Default mati total.** Config MinIO kosong = tidak ada percobaan koneksi
  sama sekali, app berjalan seolah fitur ini tidak ada.
- **Meeting hasil pull read-only untuk pemrosesan.** Cuma device yang
  merekam yang boleh Transkrip/Ringkas/Coba Lagi — mencegah dua device
  memproses meeting yang sama secara bersamaan. Menghapus salinan lokal
  tetap boleh (§10) karena hanya memengaruhi device yang menghapus.
- **File audio TIDAK perlu diunduh device lain.** App ini belum punya fitur
  putar audio — device lain cukup baca transkrip/ringkasan (teks, sudah ada
  di manifest) dan, kalau perlu, unduh docx on-demand. WAV tetap di-upload
  saat push (untuk backup/redundansi milik device perekam sendiri), tapi
  tidak pernah ditarik oleh device lain.
- **Pakai kolom yang sudah ada.** Tidak ada kolom "remote key" baru —
  `Meeting.recording_dir` + `Meeting.device_id` (dari spec device identity)
  sudah cukup untuk menentukan lokasi objek MinIO secara deterministik.

## 3. Struktur Bucket

```
<bucket>/<device_id>/<meeting_dir_uuid>/
  manifest.json   # meeting + transcript segments + speaker labels + summary
  mic.wav
  speaker.wav
  mom.docx        # kalau sudah pernah dibuat
```

`<meeting_dir_uuid>` = basename dari `Meeting.recording_dir` (sudah unik,
di-generate `uuid.uuid4().hex` saat `start_meeting()`).

`manifest.json`:
```json
{
  "title": "...", "scheduled_time": "...", "start_time": "...", "end_time": "...",
  "status": "completed", "device_id": "...", "device_label": "Laptop Budi",
  "segments": [{"speaker_label": "...", "source": "mic|speaker", "start_ms": 0, "end_ms": 900, "text": "..."}],
  "summary": {"mom_json": "...", "has_docx": true}
}
```

## 4. Perubahan Skema

```python
class Meeting(Base):
    ...
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
```

Satu kolom baru: kapan file (WAV/docx) meeting ini **milik device ini**
terakhir sukses di-upload. Dipakai untuk skip upload ulang file yang tidak
berubah — `manifest.json` sendiri selalu di-upload ulang tiap sync (murah,
supaya status terbaru selalu ter-refresh bagi yang pull).

Meeting hasil pull: `device_id`/`device_label` diisi dari manifest (bukan
device lokal) — kolom ini sudah cukup untuk membedakan "milik saya" vs
"hasil pull" (`Meeting.device_id != Settings.device_id`), tidak perlu flag
`is_remote` terpisah.

## 5. `app/sync/minio_client.py` (baru)

```python
def is_configured(settings: Settings) -> bool: ...   # semua field MinIO terisi?
def push(session_factory, settings: Settings) -> PushResult: ...
def pull(session_factory, settings: Settings) -> PullResult: ...
def download_file(settings: Settings, device_id: str, meeting_dir: str, filename: str, dest: Path) -> None: ...
```

`minio` package (client resmi S3-compatible, ringan) sebagai dependency
baru, di-import lazy di dalam fungsi (pola yang sama seperti
`pyaudiowpatch`/`silero_vad` di codebase ini) — tidak menambah beban impor
kalau fitur ini tidak dipakai.

**push()**: untuk tiap `Meeting` dengan `device_id == settings.device_id` —
upload `manifest.json` (selalu). Kalau `synced_at is None` atau file lokal
berubah sejak `synced_at`, upload juga `mic.wav`/`speaker.wav`/`mom.docx`
yang ada, lalu update `synced_at = now()`.

**pull()**: `list_objects(bucket, recursive=True)`, cari
`*/manifest.json` yang prefix `<device_id>`-nya BUKAN
`settings.device_id` DAN belum ada `Meeting` lokal dengan
`(device_id, recording_dir basename)` yang sama. Untuk tiap manifest baru:
download, parse, `INSERT` `Meeting` + `Speaker` + `TranscriptSegment` +
`Summary` (kalau ada) — `recording_dir` diisi path lokal yang BELUM tentu
ada filenya (`recordings_dir/<meeting_dir_uuid>`), file fisik baru diambil
saat dibutuhkan (§6).

## 6. Unduh On-Demand

`HistoryView._handle_download` (tombol "Unduh Docx"): kalau meeting adalah
hasil pull (`device_id != local`) dan file docx belum ada di
`recording_dir` lokal, panggil `download_file(...)` dulu (progress lewat
pola busy-button yang sudah ada), baru `os.startfile(...)` seperti biasa.
Meeting milik sendiri tidak berubah sama sekali (file sudah lokal).

## 7. Perubahan UI

- **`app/ui/history_view.py`**: tombol baru **"Sync Sekarang"**, selalu
  terlihat (tidak tergantung seleksi meeting), disembunyikan total kalau
  `is_configured(settings)` bernilai False (default). Jalan di background
  thread (pola `_run_in_background` yang sudah ada), status ringkas di
  `_status_label` ("Sync selesai: 3 diunggah, 1 ditarik" / pesan error).
- **`_update_action_panel`**: kalau `meeting.device_id != local device_id`
  → sembunyikan Transkrip/Ringkasan/Coba Lagi (aksi pemrosesan, hanya milik
  device perekam), tapi **Hapus tetap tersedia** (menghapus salinan/baris
  lokal saja — lihat §10) dan Lihat Transkrip + Unduh Docx tetap aktif.
- **`app/ui/setup_wizard.py`**: expander baru **"Sinkronisasi MinIO
  (lanjutan)"** — endpoint, access key, secret key, nama bucket, semua
  opsional, kosong = fitur mati.

## 8. Error Handling

- MinIO tidak terjangkau / kredensial salah saat klik Sync → tangkap
  exception, tampilkan pesan jelas di status label, tidak ada apa pun yang
  berubah di DB lokal (push/pull per-meeting dibungkus try/except sendiri,
  satu meeting gagal tidak menggagalkan seluruh batch).
- Klik Sync dobel sebelum yang pertama selesai → tombol disabled
  sinkron sebelum thread mulai (pola yang sama seperti tombol aksi
  Riwayat lain).
- Unduh docx on-demand gagal (network putus) → pesan error di status,
  meeting tetap ada di Riwayat, bisa dicoba unduh lagi kapan pun.

## 9. Testing

- `tests/sync/test_minio_client.py` (baru): mock `Minio` client (tidak
  butuh server MinIO asli, konsisten dengan konvensi test suite yang ada).
  - `push()`: meeting milik device lain tidak ikut ter-upload; file yang
    `synced_at`-nya masih baru tidak di-upload ulang; manifest selalu
    di-upload.
  - `pull()`: manifest device lain yang belum ada → jadi `Meeting` baru
    lokal dengan `device_id`/`device_label` dari manifest; manifest yang
    sudah pernah di-pull tidak dobel; manifest dari `device_id` sendiri
    diabaikan.
- `tests/ui/test_history_view.py`: tombol Sync tersembunyi kalau MinIO
  belum dikonfigurasi; meeting dengan `device_id` asing hanya menampilkan
  Lihat Transkrip + Unduh Docx.

## 10. Di Luar Cakupan (v1)

- Putar audio (baik lokal maupun dari device lain) — app belum punya fitur
  ini sama sekali di luar spec ini.
- Sync otomatis/berkala di background.
- Resolusi konflik untuk meeting yang "diklaim" lebih dari satu device
  (tidak mungkin terjadi selama `start_meeting()` selalu men-stamp
  `device_id` lokal dan pull tidak pernah menulis ulang milik sendiri).
- Hapus meeting hasil pull dari MinIO (tombol Hapus di Riwayat untuk
  meeting hasil pull hanya menghapus salinan/baris lokal, tidak menyentuh
  objek di bucket milik device pemilik).
