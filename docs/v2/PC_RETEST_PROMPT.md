# Prompt uji ulang di PC (setelah perbaikan `b2374c1`)

Salin blok di bawah ke Claude di PC Windows + GPU. Bagian 1 harus lulus sebelum bagian lain berarti.
Butir **[ANDA]** butuh tangan/telinga/layar Anda; Claude diminta berhenti dan menunggu Anda di butir itu.

````text
Kamu menguji ULANG aplikasi "Rekamind" setelah perbaikan. Balas dalam Bahasa Indonesia. Jujur: tandai tiap butir
LULUS / GAGAL / TIDAK BISA DIUJI (alasan). Untuk GAGAL sertakan pesan galat persis + 20 baris log relevan.
Jangan memperbaiki kode (kecuali satu hal: memasang prasyarat). Jangan menulis rahasia (kunci API, token) di laporan.

## Konteks
- Repo https://github.com/handokoaji/rekamind , branch `v2/core-api`, commit `b2374c1` atau lebih baru.
  `git pull` lalu baca `docs/v2/PC_TEST_RESULTS.md` (bagian 5 = temuan lama, bagian 8 = perbaikan yang diklaim).
- Perbaikan hanya terbukti di Linux. Tugasmu membuktikan atau membantahnya di Windows + GTX 1080 Ti.
- Data uji lama masih ada di folder scratchpad sesi sebelumnya (rekaman 201 dtk, rapat 52 mnt `recordings/042daa73…`).
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (recordings\, backend\logs\backend.log, backend\engine-pack\).

## Langkah 0. Bangun & pasang bersih
1. `git pull`; `.venv\Scripts\activate`; `pip install -e "server[dev,postgres]" pyinstaller`
   (PENTING: `av` kini harus 16.x: `pip list | findstr /i " av "`).
2. `python scripts/build_desktop.py` ; catat durasi/ukuran installer.
3. `python scripts/smoke_backend.py desktop\src-tauri\resources\backend\rekamind-backend.exe`
   Harus mencetak "Smoke test lulus." dengan **14** baris ok, termasuk baris
   "pip can locate its own resources and the stdlib the ML packages need is bundled".
   Bila baris itu GAGAL: salin JSON-nya (field error/missing_stdlib) dan HENTIKAN, itu temuan #1.
4. Hapus instalasi lama + data uji: tutup app, uninstall, hapus `%LOCALAPPDATA%\id.rekamind.desktop\backend\engine-pack`
   (jangan hapus `recordings\`). Pasang installer baru.
5. Pastikan tidak ada proses `rekamind-backend.exe` yatim: `Get-Process rekamind*`.

## BAGIAN 1. Verifikasi tiap perbaikan (urutan penting)
R1 [pip beku]. Tanpa UI dulu, perintah CLI dari folder terpasang:
   `"%LOCALAPPDATA%\Rekamind\backend\rekamind-backend.exe" engines selftest` -> `"ok": true`.
   (Lokasi `resources\backend` bisa berbeda; cari `rekamind-backend.exe`.) Lalu
   `... engines selftest --no-fix` HARUS gagal dengan DistlibException (itu bukti perbaikannya yang bekerja).
R2 [pasang mesin dari UI, NVIDIA]. Buka app -> Pengaturan -> Mesin transkripsi -> centang "pemisah pembicara"
   -> "Pasang untuk NVIDIA GPU". Catat: progres tampil dan bergerak? waktu total (±15 menit), ukuran `engine-pack`,
   path terpanjang (`Get-ChildItem -Recurse ... | sort Length`), galat jalur panjang/antivirus?
   Setelah selesai: "Uji mesin" harus menampilkan faster-whisper + "GPU NVIDIA terdeteksi: 1".
   Lalu periksa versi av di pack: `engine-pack\av-*.dist-info` harus 16.x (bukan 19).
R3 [batalkan]. Klik "Pasang ulang untuk CPU", tunggu progres jalan, klik "Batalkan". Harus berhenti < 5 detik,
   tidak ada proses pip tersisa, dan "Uji mesin" pada pack lama tetap berfungsi (atau pasang ulang bersih).
R4 [transkripsi pada pack segar, tanpa trik]. Isi kunci API Groq, model Whisper `large-v3`, perangkat Otomatis.
   Proses rekaman 201 dtk dari data uji lama (unggah via "Rapat baru" bila perlu). Harapan: selesai tanpa
   `metadata_errors`. Lihat `backend.log`: baris "loading whisper ... on cuda (int8)" -> ARTINYA `auto` kini
   memilih int8 di Pascal. Ukur VRAM puncak (`nvidia-smi -l 1`): target ~4-5 GB (dulu 10,75 GB).
R5 [diarisasi di backend beku]. Dengan pack berisi diarisasi + token Hugging Face + diarizer `pyannote`:
   proses rekaman yang sama. Harapan: SPEAKER_00/01 muncul. Bila gagal, salin galat PERSIS; rapat harus tetap
   berstatus "Perlu ditinjau" dengan banner kuning "Pemisah pembicara gagal ..." (bukan "gagal total").
   Catat modul yang hilang bila ada (`No module named ...`).
R6 [LLM batas TPM]. Proses rapat 52 menit (`recordings/042daa73...`) dengan kunci Groq tier gratis (8000 TPM):
   Harapan: selesai (potongan dibelah/menunggu) ATAU transkrip tersimpan + banner "Ringkasan dan task belum dibuat"
   + tombol "Buat ulang ringkasan". Bila banner muncul, klik tombol: harus TIDAK mentranskripsi ulang (cepat) dan
   menghasilkan ringkasan. Catat waktu, jumlah segmen (~629), ada task?
R7 [OOM]. (opsional) buka game/aplikasi yang memakai ±8 GB VRAM lalu proses lagi: harus tidak crash
   (log "out of memory ... retrying").
R8 [health polling]. Setelah app dibuka bersih: `Select-String "GET /api/health" backend.log | measure`
   dalam 20 detik pertama. Dulu 1764; sekarang harus puluhan paling banyak.
R9 [cargo test di Windows]. `cd recorder; cargo test --release --no-fail-fast`
   Harapan: SEMUA lulus, termasuk `a_recording_in_progress_cannot_be_discarded_or_listed_as_pending` dan
   `ui_state_json_matches_the_golden_contract_file`. Salin ringkasan "test result" tiap berkas.
   Bila git checkout masih CRLF: `git rm --cached` tidak perlu; `.gitattributes` sudah memaksa LF (cek
   `git ls-files --eol desktop/contract/ui-state.json`).
R10 [data-loss, manual]. Mulai rekaman (Ctrl+Alt+R), lalu di jendela app buka Riwayat/Rekaman belum
   terunggah: rekaman yang sedang berjalan TIDAK boleh tampil di sana dan tidak boleh punya tombol hapus aktif.
R11 [bench]. `python -m rekamind_server.bench <wav> --model small --device auto` -> harus jalan (pack otomatis
   dipakai bila ada) dan `peak_rss_mb` > 0.
R12 [login pertama setelah boot]. (opsional, bila server Google dipasang) restart PC, login dalam 5 menit:
   tidak boleh "unknown signing key".
R13 [pytest di Windows]. `cd server; pytest -q` -> semua lulus (170).

## BAGIAN 2. Yang belum pernah teruji (butuh tangan Anda)
A5 [ANDA] cabut/pasang headset saat merekam: "menyambung ulang", rekaman lanjut.
A6 [ANDA] matikan paksa saat merekam (Task Manager). Buka lagi: rekaman muncul di "belum terunggah" dengan
   penanda crash; WAV bisa diputar; TIDAK ada `rekamind-backend.exe` yatim 10 detik setelah itu.
A9 [ANDA] tutup via tray -> Keluar, buka lagi: kunci API/token HF masih tersimpan (kotak bertopeng)? (Credential Manager)
A10 [ANDA] tray: ikon ada, klik membuka jendela, menu Keluar bekerja; tidak ada jendela konsol hitam berkedip.
M1 [ANDA] bicara ke mikrofon 1 menit + putar video: pembicara "ME" muncul dan teksnya benar (mic nyata dengan suara).
T1-T4 [ANDA] tab Task pada rapat hasil R6: konfirmasi/ubah PIC & tenggat/tolak/batalkan; "Salin Markdown" dan
   "Unduh JSON" hanya berisi task terkonfirmasi (cek `rekamind.tasks/v1`); tombol putar pada kutipan bukti
   melompat ke waktu benar; rapat 52 mnt: tab Transkrip dan Task mulus saat di-scroll.
W1 Tes web: `cd web; npm ci; npx vitest run` (harus 61 lulus) dan `npx playwright install chromium; npx playwright test`
   (22 lulus). Dulu tidak dijalankan di Windows.

## Laporan akhir (format wajib)
Tabel: butir | status | bukti (angka/pesan/nama file) | catatan.
Lalu: (1) apakah tiap temuan lama #1-#10 TERBUKTI TERATASI / MASIH ADA, (2) temuan baru berurutan keparahan,
(3) yang tidak bisa diuji, (4) berkas yang perlu dikirim ke pengembang (backend.log, hasil cargo test,
keluaran selftest, screenshot galat). Simpan sebagai `docs/v2/PC_RETEST_RESULTS.md`, commit, push ke `v2/core-api`.
````
