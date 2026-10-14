# Prompt untuk menguji Rekamind di PC

Salin seluruh blok di bawah ke Claude (Claude Code di terminal PC Anda, atau Claude desktop dengan akses komputer).
Jalankan satu bagian per sesi supaya hasilnya rapi. Bagian yang butuh tangan atau telinga Anda ditandai **[ANDA]**.

---

````text
Kamu adalah penguji untuk aplikasi "Rekamind" (perekam rapat -> transkrip -> ringkasan -> task).
Balas selalu dalam Bahasa Indonesia. Jujur: laporkan apa adanya, jangan menganggap lulus sesuatu yang tidak
benar-benar kamu lihat/jalankan. Tandai tiap butir: LULUS / GAGAL / TIDAK BISA DIUJI (beri alasan). Untuk GAGAL
sertakan pesan galat persisnya dan 20 baris terakhir log yang relevan. Jangan memperbaiki kode; tugasmu menguji
dan melaporkan. Jangan mengirim rahasia (kunci API, token) ke mana pun dan jangan menuliskannya di laporan.

## Konteks
- Repo: https://github.com/handokoaji/rekamind , branch `v2/core-api`. Baca `docs/v2/ARCHITECTURE.md`,
  `docs/INSTALL.md`, `docs/AUTH.md`, dan `docs/v2/PC_TEST_CHECKLIST.md`.
- Sistem: perekam Rust (WASAPI di Windows) + aplikasi desktop Tauri + backend Python yang dibekukan (PyInstaller)
  di dalam installer. Mesin transkripsi (faster-whisper) TIDAK ada di installer; dipasang dari Pengaturan.
- Semua yang bisa diuji tanpa perangkat sudah lulus di sandbox Linux. Yang belum pernah dijalankan siapa pun:
  Windows, GPU NVIDIA, model Whisper nyata, Google asli. Itu yang kamu uji.
- Data aplikasi (Windows): `%LOCALAPPDATA%\id.rekamind.desktop\` -> `recordings\` (WAV) dan `backend\`
  (`logs\backend.log`, `engine-pack\`, `models\`, SQLite).

## Langkah 0: siapkan installer
Pilih satu:
(a) Unduh artifact installer dari GitHub Actions workflow `v2-ci` (job `desktop`, windows-latest) bila ada
    yang hijau. (Workflow ini BELUM PERNAH berjalan; bila gagal, catat log langkah yang gagal sebagai temuan.)
(b) Bangun sendiri di PC ini. Prasyarat: Node 22, Python 3.13, Rust stable (MSVC), WebView2.
    git clone ... && cd rekamind && git checkout v2/core-api
    py -3.13 -m venv .venv && .venv\Scripts\activate
    pip install -e "server[dev]" pyinstaller
    python scripts/build_desktop.py                      # menghasilkan installer NSIS
    python scripts/smoke_backend.py desktop\src-tauri\resources\backend\rekamind-backend.exe
Catat: durasi build, ukuran installer (.exe), dan semua peringatan/galat. Smoke test harus mencetak
"Smoke test lulus." (12 baris "ok"). Bila gagal, itu temuan #1: berhenti dan laporkan.

## BAGIAN A: Windows tanpa GPU khusus
A1. Pasang installer. Catat: apakah SmartScreen/antivirus memperingatkan (diharapkan; belum ditandatangani).
    Apakah ada pemasangan per-pengguna tanpa admin (installMode currentUser)?
A2. Buka aplikasi. Harus ada jendela + ikon tray. Tidak boleh ada jendela konsol hitam yang berkedip.
    Periksa `%LOCALAPPDATA%\id.rekamind.desktop\backend\logs\backend.log` ada isinya setelah backend menyala.
A3. [ANDA] Isi nama di Pengaturan. Tekan Ctrl+Alt+R, putar video (YouTube) + bicara ke mikrofon 1 menit,
    tekan Ctrl+Alt+R lagi. Harapan: kartu "terunggah", rapat muncul "Siap diproses", dan (karena mesin belum
    dipasang) kartu berkata "Belum diproses: ..." + banner "Mesin transkripsi belum dipasang".
    Selama merekam, dengan jendela DITUTUP, ukur di Task Manager (Details) proses `rekamind.exe`:
    CPU% dan "Memory (private working set)" tiap ~10 detik selama 1 menit. Target: RAM < 100 MB, CPU ~0-1%.
    Pastikan TIDAK ada proses `rekamind-backend.exe` selama merekam.
A4. [ANDA] Putar kedua WAV di `recordings\<folder>\` : `mic.wav` harus berisi suara Anda, `speaker.wav` suara video.
    Beri tahu panjangnya (harus ~sama dengan lama rekaman). Ini uji WASAPI loopback.
A5. [ANDA] Saat merekam, cabut/pasang headset. Harapan: sumber yang terputus tampil "menyambung ulang",
    perekaman tidak berhenti, dan setelah dipasang lagi kembali normal.
A6. Mulai rekaman lalu matikan paksa (Task Manager -> End task `rekamind.exe`; juga bunuh
    `rekamind-backend.exe` bila ada). Buka aplikasi lagi. Harapan: rekaman muncul di "Rekaman yang belum
    terunggah" dengan penanda crash, WAV bisa diputar, dan tombol Unggah berfungsi. Pastikan tidak ada
    `rekamind-backend.exe` yatim 10 detik setelah aplikasi dimatikan paksa (backend harus mati sendiri).
A7. Pengaturan -> Mesin transkripsi -> "Pasang untuk CPU". Catat: waktu total, ukuran folder `engine-pack`,
    apakah progres/log tampil dan bergerak, apakah ada galat jalur panjang (>260 karakter) atau antivirus
    memblokir. Setelah selesai harus muncul "Terpasang · CPU" dan hasil "Uji mesin" menyatakan berfungsi.
    Uji juga "Batalkan" di tengah pemasangan kedua (pasang ulang): harus berhenti < 5 detik tanpa merusak.
A8. [ANDA] Isi kunci API layanan ringkasan (mis. Groq) di Pengaturan. Pilih model Whisper `small`. Klik
    "Unduh model small sekarang", lalu proses rapat 1 menit dari A3 (tombol Proses). Harapan: transkrip
    bahasa Indonesia yang masuk akal, ada pembicara "ME" (mic) dan satu pembicara untuk speaker, ringkasan dan
    task terisi. Catat waktu proses dan apakah timestamp transkrip sinkron saat diputar.
A9. Tutup aplikasi sepenuhnya (tray -> Keluar), buka lagi. Kunci API masih tersimpan (kotak menampilkan
    topeng) dan proses jalan tanpa mengetik ulang? Bila tidak, catat (Credential Manager).
A10. Tutup jendela saja (bukan Keluar): ikon tray tetap ada, merekam via hotkey tetap bisa, RAM kecil.

## TAB TASK (setelah A)
T1. Buka rapat hasil A8 -> tab Task. Konfirmasi satu task, ubah PIC dan tenggatnya, tolak satu, batalkan satu.
    Harapan: perubahan tersimpan setelah muat ulang. "Salin Markdown" dan "Unduh JSON" hanya berisi task
    yang DIKONFIRMASI; periksa isi JSON (`rekamind.tasks/v1`): ada PIC, tenggat, estimasi, kutipan bukti.
T2. Klik "putar dari" pada kutipan bukti sebuah task: audio melompat ke waktu yang benar.
T3. Beban: jalankan satu rapat 60+ menit (atau unggah file rekaman panjang lewat tombol Rapat baru) dan buka
    tab Transkrip dan Task. Catat apakah scroll mulus dan memori jendela (Task Manager -> proses WebView2).
T4. Tab Task pada daftar besar: bila ada rapat dengan > 40 task, daftar harus tetap bisa di-scroll dan
    diedit (konfirmasi/ubah) tanpa lag.

## Laporan akhir (format wajib)
Tabel: butir | status | bukti (angka/pesan galat/nama file) | catatan.
Lalu: (1) 5 temuan terpenting berurutan keparahan, (2) hal yang TIDAK bisa kamu uji, (3) perintah/berkas
yang perlu saya kirim ke pengembang (log: backend.log, hasil `rekamind-rec record --stats`, screenshot galat).
````

---

## Bagian lain (sesi terpisah)

**B (GPU NVIDIA):** ganti A7 menjadi "Pasang untuk NVIDIA GPU", lalu: "Uji mesin" harus menyatakan
`GPU NVIDIA terdeteksi`; proses rekaman 30-60 menit dengan `large-v3` dan catat waktu serta puncak VRAM
(`nvidia-smi`); bandingkan WER kasar dengan transkrip referensi; coba pemisah pembicara (centang saat pasang,
token Hugging Face, setujui syarat `pyannote/speaker-diarization-3.1`).

**C (Google asli):** ikuti `docs/AUTH.md` untuk membuat OAuth client, jalankan `docker compose up -d --build`
dengan `.env`, uji login dari browser dan dari aplikasi desktop (mode Server terpisah), dua akun berbeda tidak
boleh melihat rapat satu sama lain, super admin bisa mengelola pengguna.

**D (server):** MinIO atau SeaweedFS sebagai `REKAMIND_STORAGE=s3`, Postgres sebagai `REKAMIND_DATABASE_URL`.
