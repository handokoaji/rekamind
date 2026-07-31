# Meeting Recorder — Fase 3 (Riwayat Meeting & Proses Manual) Design Spec

Date: 2026-07-31

## 1. Purpose

Fase 1+2 (selesai) merekam lalu langsung menjalankan seluruh pipeline berat
(transkrip large-v3 + diarisasi + Groq + docx) begitu "Stop Rekam" diklik —
window terkunci (`state="processing"`) sampai semuanya selesai, dan meeting
baru tidak bisa dimulai sampai itu tuntas. Ini terasa berat kalau ada meeting
lanjutan segera setelah satu meeting selesai.

Fase 3 memisahkan **merekam** dari **memproses**: Stop hanya menyimpan WAV
dan mengunci meeting sebagai "siap diproses". Transkripsi dan ringkasan jadi
aksi manual, dipicu dari halaman riwayat meeting, kapan saja — bisa langsung,
bisa nanti, bisa sambil meeting lain sedang direkam.

Fase 3 juga menyerap:
- Crash recovery yang sudah dibangun terpisah (`app/pipeline/recovery.py`,
  `Meeting.recording_dir`) — meeting yang "ketinggalan" di status
  `recording`/`processing` karena crash cukup di-reset ke `recorded` saat
  startup, lalu muncul di Riwayat siap diproses manual.
- Logging ke file (`app/logging_setup.py`, sudah ada) — tahap baru di fase
  ini (`transcribe_and_diarize`, `summarize_and_export`, retry) log ke
  `logs/app.log` yang sama.

## 2. Prinsip Utama

- **Stop itu murah.** Setelah Stop, satu-satunya kerja adalah menutup WAV dan
  update status DB — instan, tidak ada model yang dimuat.
- **Proses manual, per-tahap, per-meeting.** Transkripsi dan ringkasan adalah
  dua tombol terpisah di riwayat, masing-masing hanya aktif kalau tahap
  sebelumnya sudah selesai.
- **Meeting baru tidak pernah diblokir oleh proses meeting lama.** Model live
  (kecil, dipakai saat rekam) dan model batch (besar, dipakai saat Transkrip
  diklik dari riwayat) adalah instance terpisah — boleh jalan bersamaan.
- **Gagal itu bisa dicoba lagi, tanpa rekam ulang.** Kegagalan di satu tahap
  (mis. Groq timeout) tidak menghanguskan tahap sebelumnya yang sudah
  berhasil; tombol "Coba Lagi" mengulang HANYA tahap yang gagal.

## 3. Status Meeting (state machine)

```
recording -> recorded -> transcribing -> transcribed -> summarizing -> completed
                                                                  \
   (crash di titik manapun sebelum "recorded") --[recovery]--> recorded
```

Kegagalan di `transcribing` atau `summarizing` pindah ke `failed`, dengan
`Meeting.error_message` (kolom baru) dan `Meeting.failed_stage` (kolom baru,
nilai `"transcribe"` atau `"summarize"`) menentukan tahap mana yang diulang
tombol "Coba Lagi".

`scheduled` tetap ada sebagai default sesaat sebelum `start_recording()`
dipanggil (sudah begitu sejak Fase 1, tidak berubah).

## 4. Komponen Baru/Modifikasi

```
app/storage/models.py         # (mod) Meeting: + error_message, + failed_stage
app/storage/repository.py     # (mod) query riwayat + update status granular;
                               # (sudah ada dari recovery) find_abandoned_meetings
app/pipeline/finalize.py      # (mod) dipecah jadi transcribe_and_diarize() dan
                               # summarize_and_export(), masing-masing
                               # membaca/menyimpan lewat DB (bukan lewat variabel
                               # in-memory) supaya bisa dipanggil terpisah kapan pun
app/pipeline/recovery.py      # (mod) recovery cukup reset status -> "recorded",
                               # tidak lagi memanggil finalize langsung
app/ui/controller.py          # (mod) stop_meeting() berhenti di "recorded", tidak
                               # lagi memanggil finalize; + start_transcribe(),
                               # start_summarize(), retry() untuk dipanggil dari
                               # riwayat, masing-masing background-thread seperti
                               # start/stop_meeting sekarang
app/ui/history_view.py        # (baru) Treeview + panel aksi, baca riwayat dari DB,
                               # tombol per status, panel "Lihat Transkrip"
app/ui/window.py              # (mod) dua tab: "Meeting Baru" (isi sekarang, tidak
                               # berubah) dan "Riwayat" (history_view.py)
app/main.py                   # (mod) wiring controller baru + panggil recovery
                               # (reset status) sekali saat startup, tanpa dialog
```

Tidak berubah: `app/audio/*`, `app/live/*` (live preview selama rekam persis
seperti Fase 2), `app/asr/*`, `app/diarization/diarizer.py`,
`app/pipeline/merge.py`, `app/summarization/*`.

**Digantikan di tab "Meeting Baru":** progress bar + label tahap + tombol
"Buka Hasil (docx)" yang ada sekarang (`app/ui/window.py`,
`_progress_bar`/`_open_docx_button`) itu untuk alur lama (auto-proses
setelah Stop, state `processing`→`done`). Di Fase 3, Stop langsung ke
`idle` — state `processing`/`done` tidak pernah lagi tercapai dari tab ini,
jadi widget-widget itu dihapus dari tab Meeting Baru. Fungsinya (progress
per tahap, buka docx) pindah ke panel aksi tab Riwayat, per-meeting.

## 5. Data Flow

**Rekam (tidak berubah dari Fase 1/2) → Stop:**

1. `stop_meeting()`: `recorder.stop()` menutup WAV, live session dihentikan
   (Fase 2, tidak berubah), `stop_recording()` + `save_recording_file()`
   dipanggil seperti sekarang, status di-set `"recorded"`. **Tidak** memanggil
   `finalize_fn` lagi. UI langsung `state="idle"` — bisa langsung mulai
   meeting baru.

**Riwayat:**

2. Tab "Riwayat" query `repo.list_meetings()` (sudah ada), tampil di
   Treeview: Judul, Tanggal (WIB), Status, Durasi. Polling `root.after`
   ringan (mis. tiap 2 detik saat tab ini aktif) me-refresh baris yang
   sedang `transcribing`/`summarizing` supaya statusnya update tanpa perlu
   klik refresh manual.
3. Pilih baris → panel aksi menampilkan tombol sesuai status:
   - `recorded` → tombol **Transkrip**
   - `transcribing` → teks "Sedang transkrip..." (tidak ada tombol)
   - `transcribed` → tombol **Ringkasan**, + tombol **Lihat Transkrip**
   - `summarizing` → teks "Sedang membuat ringkasan..." (tidak ada tombol)
   - `completed` → tombol **Unduh Docx**, + **Lihat Transkrip**
   - `failed` → pesan error + tombol **Coba Lagi**
4. **Transkrip** diklik → background thread memanggil
   `transcribe_and_diarize(session_factory, meeting_id, mic_wav, speaker_wav,
   transcriber, diarizer)`: load model batch (lazy, di-cache sama seperti
   sekarang), transkrip+diarisasi+simpan segmen final, status →
   `"transcribed"`. Gagal → status `"failed"`, `failed_stage="transcribe"`,
   `error_message` diisi.
5. **Ringkasan** diklik → background thread memanggil
   `summarize_and_export(session_factory, meeting_id, meeting_title,
   meeting_date, docx_output_path, summarizer)`: baca segmen final dari DB
   (bukan dari memori — bisa jadi ini proses baru/app baru dibuka), susun
   transcript_text, Groq → docx (nama file format
   `YYYY-MM-DD-Judul-Meeting.docx`, tidak berubah), status → `"completed"`.
   Gagal → `"failed"`, `failed_stage="summarize"`.
6. **Coba Lagi** → panggil ulang `transcribe_and_diarize` atau
   `summarize_and_export` sesuai `failed_stage`.
7. **Unduh Docx** → `os.startfile(docx_path)`, pola sama seperti tombol
   sekarang di tab Meeting Baru.
8. **Lihat Transkrip** → baca `TranscriptSegment` (`is_final=True`) +
   `Speaker.label` dari DB untuk meeting itu, render read-only di panel
   (format sama seperti `transcript_view`: `"{label}: {text}"` per baris).

**Startup (recovery, tanpa dialog):**

9. `main()` sekali di awal: `repo.find_abandoned_meetings()` (status
   `recording`/`processing`) → masing-masing di-reset ke status `"recorded"`
   kalau `recording_dir` + WAV ada, atau `"failed"` (`failed_stage`
   ditentukan dari status lama: `recording`→`"transcribe"`,
   `processing`→`"summarize"`) kalau file tidak ditemukan. Tidak ada proses
   berat dijalankan otomatis — meeting itu tinggal muncul di Riwayat seperti
   meeting lain yang menunggu diproses manual. Ini menggantikan
   `recover_abandoned_meetings()` yang lama (yang langsung memanggil
   finalize) — fungsi itu disederhanakan jadi reset-status saja.

## 6. Konkurensi

Live model (Fase 2, dipakai saat rekam) dan model batch (dipakai
`transcribe_and_diarize`) adalah instance terpisah sejak Fase 2 — boleh jalan
bersamaan tanpa perubahan. Kalau user klik Transkrip di DUA meeting berbeda
sekaligus dari Riwayat, keduanya juga boleh jalan bersamaan (background
thread masing-masing) — model batch (`load_models()`) sudah singleton
ter-cache, dipakai bersama oleh kedua thread (thread-safety transkripsi
CTranslate2/pyannote per-call sudah aman dipakai berurutan dari model yang
sama; kalau dua thread memanggil `.transcribe()`/`.diarize()` di saat sama
persis, GIL Python + operasi C++ di baliknya tidak akan corrupt state, hanya
lebih lambat karena berebut GPU/CPU yang sama — tidak perlu locking
tambahan).

## 7. Error Handling

- Kegagalan di `transcribe_and_diarize`/`summarize_and_export` tidak pernah
  menghapus data tahap sebelumnya yang sudah berhasil (pola yang sama persis
  seperti `finalize_meeting` sekarang: masing-masing tahap commit sendiri).
- Live preview / rekam (Fase 1/2) sama sekali tidak berubah oleh fase ini.
- Kalau `mic.wav`/`speaker.wav` hilang (mis. folder `recordings/` dihapus
  manual) saat Transkrip diklik → gagal dengan pesan jelas, status
  `"failed"`, `failed_stage="transcribe"`.

## 8. Testing

- `app/pipeline/finalize.py` (split): test `transcribe_and_diarize()` dan
  `summarize_and_export()` terpisah — pola sama seperti test
  `finalize_meeting` sekarang (in-memory SQLite, fake transcriber/diarizer/
  summarizer), plus test bahwa `summarize_and_export` membaca transkrip dari
  DB (bukan butuh argumen transkrip in-memory).
- `app/pipeline/recovery.py` (disederhanakan): test reset-status untuk
  meeting `recording`→`recorded` (kalau file ada) atau →`failed` (kalau
  tidak), dan `processing`→`recorded` juga (segmen final belum tentu
  tersimpan kalau crash di tengah `transcribe_and_diarize` versi lama —
  perlu re-cek: kalau status lama `processing`, segmen final SUDAH tersimpan
  dari fase Fase 1/2 lama, jadi harusnya reset ke `"transcribed"` bukan
  `"recorded"` — lihat catatan di bawah).
- `app/ui/history_view.py`: fake controller + fake daftar meeting, verifikasi
  tombol yang muncul sesuai status, klik tombol memanggil method controller
  yang benar dengan meeting_id yang benar.
- `app/ui/controller.py`: test `stop_meeting()` berhenti di status
  `"recorded"` (tidak lagi memanggil finalize), test `start_transcribe()`/
  `start_summarize()`/`retry()` masing-masing.

**Catatan penting untuk plan:** status lama Fase 1/2 cuma punya
`recording`/`processing`/`completed`/`failed` — tidak granular seperti Fase 3.
Recovery untuk meeting yang crash di status lama `"processing"` (artinya
sudah lewat transkripsi, sedang di tahap ringkasan) harus reset ke
`"transcribed"`, bukan `"recorded"`, supaya tidak transkrip ulang yang
sebenarnya sudah berhasil. Ini perlu dicek lewat ada/tidaknya
`TranscriptSegment(is_final=True)` untuk meeting itu, bukan cuma dari nilai
status lama saja (status lama `"processing"` dari Fase 1/2 bisa juga berarti
crash SEBELUM transkripsi selesai, karena `finalize_meeting` lama set
`"processing"` di awal Stop, sebelum transkripsi jalan sama sekali).

## 9. Di Luar Skop Fase 3

- Rename speaker dari UI — tetap ditunda.
- Hapus/edit meeting dari riwayat — tidak diminta, tidak dibangun.
- Notifikasi/toast saat proses background selesai (mis. tray notification
  "Transkrip meeting X selesai") — bisa jadi permintaan lanjutan, di luar
  skop sekarang; status di Riwayat sudah cukup lewat polling refresh.
- Batasan jumlah proses batch bersamaan (mis. antre otomatis kalau user
  klik Transkrip di banyak meeting sekaligus) — dibiarkan tanpa batas untuk
  sekarang sesuai keputusan "boleh bersamaan"; jika VRAM jadi masalah nyata
  di pemakaian sehari-hari, ini jadi kandidat Fase 4.
