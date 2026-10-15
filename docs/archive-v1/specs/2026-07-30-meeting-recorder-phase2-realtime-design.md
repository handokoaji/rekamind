# Meeting Recorder — Fase 2 (Real-time Streaming) Design Spec

Date: 2026-07-30

## 1. Purpose

Fase 1 (selesai, diverifikasi end-to-end di hardware GTX 1080 Ti) merekam
audio lalu memproses semuanya secara batch setelah "Stop Rekam" — user tidak
melihat apa pun sampai rekaman selesai. Fase 2 menambahkan **live preview**:
teks transkrip muncul saat rapat berlangsung, dengan label pembicara
menyusul beberapa detik kemudian. Transkrip resmi (akurasi maksimal) tetap
dihasilkan lewat proses batch large-v3 setelah Stop, persis seperti Fase 1 —
Fase 2 murni menambah lapisan "intip cepat selama rapat", bukan mengganti
jalur akurasi Fase 1.

## 2. Prinsip Utama

- **Live preview tidak boleh mengganggu rekaman.** Kalau live pipeline error,
  rekaman (penulisan WAV) tetap jalan tanpa gangguan — hasil akhir tetap bisa
  diproses lewat batch Fase 1 seperti biasa.
- **Live preview itu draft, bukan sumber kebenaran.** Teks yang tampil selama
  rapat memakai model kecil (cepat, kurang akurat) dan disimpan sebagai draft
  (`is_final=False`). Begitu proses batch large-v3 selesai setelah Stop, draft
  dihapus dan digantikan transkrip final (`is_final=True`).
- **Diarization live = proses ulang penuh, bukan sliding window.** Supaya
  label "Speaker 1/2/3" konsisten sepanjang rapat, diarization live memproses
  ulang SELURUH `speaker.wav` yang sudah terekam sejauh ini setiap ~8 detik
  (bukan cuma window terakhir). Ini cocok untuk rapat pendek-menengah
  (< 30-45 menit); rapat sangat panjang akan membuat interval diarization
  makin lambat — di luar skop Fase 2 untuk dioptimalkan lebih jauh (catatan
  untuk Fase 3+ kalau jadi masalah nyata).

## 3. Komponen Baru

```
app/audio/capture.py       # (modifikasi) tap paralel: tiap frame yang ditulis ke WAV
                            # juga dimasukkan ke queue in-memory untuk live pipeline
app/live/vad.py            # silero-vad: deteksi batas ucapan dari stream frame di queue
app/live/pipeline.py       # orkestrasi live: queue -> VAD -> ASR kecil -> tampilkan -> draft ke DB
app/live/diarize_loop.py   # timer ~8 detik: re-diarize seluruh speaker.wav sejauh ini,
                            # cocokkan ke segmen yang sudah tampil, update label
app/storage/repository.py  # (tambah) save_draft_segments(), clear_draft_segments(meeting_id)
app/ui/window.py           # (modifikasi) transcript_view diisi live via queue+polling (root.after)
```

Tidak ada komponen Fase 1 yang diganti — `app/asr/base.py`,
`app/asr/cuda_backend.py`, `app/asr/openvino_backend.py`,
`app/diarization/diarizer.py`, `app/pipeline/merge.py`,
`app/pipeline/finalize.py` semua dipakai ulang apa adanya (model kecil untuk
live memakai class ASR backend yang sama, cuma `model_size="small"`).

## 4. Data Flow

1. User klik "Mulai Rekam" (title diisi seperti Fase 1). Selain memulai
   capture (Fase 1), controller juga:
   - Memuat model ASR kecil (`model_size="small"`, backend sesuai hardware
     terdeteksi — sama seperti model besar, cuma ukuran beda)
   - Memulai thread live pipeline
2. Audio capture (mic + speaker loopback, Fase 1) menulis tiap frame ke WAV
   **dan** memasukkan salinan frame ke queue in-memory.
3. Thread live pipeline: ambil frame dari queue → silero-vad mendeteksi
   batas ucapan → begitu satu segmen ucapan selesai (jeda diam terdeteksi),
   segmen itu ditranskrip model kecil → teks polos (tanpa label speaker)
   langsung:
   - Tampil di `transcript_view` window (lewat queue thread-safe + `root.after`
     polling, pola yang sama seperti update status Fase 1)
   - Disimpan sebagai `TranscriptSegment` draft (`is_final=False`) ke DB
4. Thread diarization live (timer ~8 detik): re-diarize seluruh
   `speaker.wav` yang terekam sejauh ini → hasil dicocokkan ke segmen yang
   sudah tampil (pakai `merge_segments` yang sudah ada di Fase 1) → baris
   yang sudah tampil di window diupdate dengan prefix label ("Anda:" untuk
   mic, "Speaker N:" untuk speaker) → draft di DB diupdate labelnya juga.
5. User klik "Stop Rekam": thread live pipeline & diarization live
   dihentikan, model ASR kecil dilepas dari memori. Proses batch Fase 1
   berjalan seperti biasa (large-v3 + diarize penuh + Groq + docx). **Sebelum
   menyimpan segmen final**, `finalize_meeting` memanggil
   `clear_draft_segments(meeting_id)` untuk menghapus semua draft
   (`is_final=False`) meeting ini, baru menyimpan segmen final
   (`is_final=True`).
6. Kalau app crash sebelum sempat Stop: draft (`is_final=False`) tetap ada
   di DB sebagai jejak parsial, WAV mentah tetap aman untuk diproses ulang
   manual nanti.

## 5. Error Handling

- Live pipeline (VAD/ASR kecil/diarization live) error di tengah jalan →
  di-log, live preview berhenti update (window tampilkan pesan singkat
  "Live preview berhenti, rekaman tetap berjalan"), **rekaman WAV tidak
  terganggu sama sekali** — proses batch setelah Stop tetap jalan normal.
- Model ASR kecil gagal dimuat saat "Mulai Rekam" → rekaman tetap dimulai
  tanpa live preview (bukan gagal total), pesan singkat ditampilkan.
- Diarization live gagal di satu interval (network/HF error sesaat) → skip
  interval itu, coba lagi di interval berikutnya; teks tanpa label tetap
  tampil (tidak hilang), hanya label yang telat.

## 6. Testing

- `app/live/vad.py`: unit test dengan fixture WAV pendek (mengandung jeda
  diam) memakai silero-vad asli (model kecil, cukup cepat untuk test) atau
  di-fake untuk test logika segmentasi murni.
- `app/live/pipeline.py`: fake ASR + fake VAD, verifikasi urutan
  queue → transkrip → tampil → draft tersimpan.
- `app/live/diarize_loop.py`: fake diarizer, verifikasi re-diarize dipanggil
  tiap interval dan label pada segmen yang sudah ada diupdate dengan benar
  (pakai `merge_segments` yang sudah diuji di Fase 1).
- `clear_draft_segments` + interaksi dengan `finalize_meeting`: test bahwa
  draft dihapus sebelum segmen final disimpan (in-memory SQLite, pola sama
  seperti test Fase 1).
- Window: fake controller mem-push teks live lewat queue, verifikasi
  `transcript_view` terisi dan terupdate saat label datang.

## 7. Di Luar Skop Fase 2

- Optimasi diarization untuk rapat sangat panjang (> 45 menit) — re-diarize
  penuh setiap 8 detik akan melambat seiring durasi bertambah; jika ini jadi
  masalah nyata, perlu pendekatan lain (sliding window atau state
  incremental) di fase berikutnya.
- Rename speaker dari UI, window riwayat meeting, retry manual summary gagal
  — tetap di Fase 3 seperti rencana awal.
- Live preview lewat browser/web — tetap Tkinter native seperti Fase 1
  (tidak ada perubahan platform UI).
