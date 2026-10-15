# Uji akhir sebelum rilis (hanya yang belum terbukti)

Versi uji: `5a19f65` atau lebih baru di `v2/core-api`. Semua yang bisa dibuktikan tanpa perangkat sudah lulus otomatis
(server 203, web 71, Playwright 23+8, Rust 93, E2E ke Postgres/SeaweedFS asli). Dokumen ini hanya memuat yang **belum
yakin**: butuh Windows, GPU, tangan/telinga Anda, atau akun asli (GitHub/GitLab/Google).

Cara pakai: salin blok "PROMPT" ke Claude di PC; butir **[ANDA]** dikerjakan oleh Anda sementara Claude menunggu dan mencatat.
Simpan hasil di `docs/v2/PC_FINAL_RESULTS.md`, commit, push.

## Gerbang rilis (go / no-go)

RILIS hanya bila SEMUA butir **[WAJIB]** lulus. Butir **[SEBAIKNYA]** yang gagal dicatat sebagai "batasan yang diketahui" di catatan rilis.

| Butir | Tingkat |
|---|---|
| G1 Pasang bersih dari installer di PC tanpa Python/Rust, aplikasi jalan | WAJIB |
| G2 Pasang mesin dari UI (CPU **dan** NVIDIA) sampai "Uji mesin" hijau | WAJIB |
| G3 Rekam ≥ 30 menit dengan jendela tertutup, tanpa proses backend, lalu unggah otomatis | WAJIB |
| G4 Rekaman tidak hilang saat app dimatikan paksa; muncul di "belum terunggah" | WAJIB |
| G5 Rekaman yang sedang berjalan tidak bisa dihapus/ditampilkan sebagai "belum terunggah" | WAJIB |
| G6 Rapat panjang (≥ 50 mnt) selesai diproses; bila LLM gagal, transkrip tersimpan + tombol "Buat ulang ringkasan" berfungsi | WAJIB |
| G7 Ekspor Word dibuka di Microsoft Word tanpa peringatan, isi lengkap, jam dalam WIB | WAJIB |
| G8 Backend tidak menyala/mati sendiri berulang saat jendela terbuka 30 menit | WAJIB |
| G9 Kunci API/token tersimpan setelah keluar-masuk app (Credential Manager) | WAJIB |
| G10 Uninstall bersih dan install ulang di atas versi lama tidak merusak data | WAJIB |
| G11 Satu task terkirim ke GitHub **atau** GitLab asli (bukan tiruan) | SEBAIKNYA (wajib bila rilis mengklaim integrasi) |
| G12 Login Google asli + isolasi dua pengguna | WAJIB untuk rilis server bersama; tidak perlu untuk rilis desktop-lokal saja |
| G13 `.deb` di Linux desktop sungguhan (tray, hotkey, merekam via PulseAudio/PipeWire) | WAJIB bila rilis Linux diklaim |
| G14 Installer ditandatangani / SmartScreen | SEBAIKNYA (catat bila tidak) |
| G15 Tab Task + pemutar bukti + mic dengan suara (pembicara "ME") | WAJIB |

## PROMPT

````text
Kamu penguji akhir sebelum rilis aplikasi "Rekamind" (perekam rapat -> transkrip -> ringkasan -> task -> ekspor/integrasi).
Balas dalam Bahasa Indonesia. Jujur: tiap butir LULUS / GAGAL / TIDAK BISA DIUJI (alasan). GAGAL wajib menyertakan pesan galat
persis + 20 baris log + langkah mereproduksi. Jangan memperbaiki kode. Jangan menulis rahasia (kunci API, token) di laporan.
Untuk butir [ANDA], berhenti, beri instruksi langkah demi langkah, tunggu jawaban saya, lalu catat jawabannya apa adanya.

## Konteks
Repo https://github.com/handokoaji/rekamind branch v2/core-api (commit 5a19f65 atau lebih baru). `git pull`.
Baca docs/v2/PC_RETEST_RESULTS.md, docs/v2/PC_FINAL_TEST.md (gerbang rilis), docs/INSTALL.md, docs/INTEGRATIONS.md.
Data aplikasi: %LOCALAPPDATA%\id.rekamind.desktop\ (recordings\, backend\logs\backend.log, backend\engine-pack\).

## Langkah 0. Bangun & pasang pada keadaan bersih
1. `pip install -e "server[dev,postgres]" pyinstaller`; `python scripts/build_desktop.py` (catat durasi, ukuran installer).
2. `python scripts/smoke_backend.py <resources\backend\rekamind-backend.exe>`: harus "Smoke test lulus." dengan **17** baris "ok"
   (termasuk "exports a Word document", "time zone database is bundled (WIB)", "integrations can encrypt tokens",
   "pip can locate its own resources ..."). Gagal = berhenti dan laporkan.
3. Idealnya di PC/VM BERSIH (tanpa Python, Rust, Node): salin hanya installer .exe, pasang. [G1]
   Catat: peringatan SmartScreen/antivirus, pasang tanpa admin, ukuran terpasang, ada/tidaknya jendela konsol berkedip. [G14]

## A. Perekaman & ketahanan data (tangan/telinga Anda)
A1 [ANDA][G3] Isi nama di Pengaturan. Ctrl+Alt+R, rekam >= 30 menit (video + bicara ke mikrofon), JENDELA DITUTUP sepanjang waktu.
   Tiap ~5 menit catat dari Task Manager (Details): rekamind.exe Private working set + CPU, dan apakah ada rekamind-backend.exe
   (harus TIDAK ada). Stop dengan Ctrl+Alt+R. Harapan: terunggah otomatis, rapat muncul "Siap diproses".
A2 [ANDA] Putar mic.wav dan speaker.wav hasilnya: mic = suara Anda, speaker = suara video, panjang sama (+/- 1 dtk). Catat.
A3 [ANDA] Cabut lalu pasang headset/mic USB saat merekam: sumber tampil "menyambung ulang", rekaman lanjut, WAV utuh. 
A4 [ANDA][G4] Mulai rekam, tunggu 30 dtk, matikan PAKSA rekamind.exe (Task Manager -> End task; juga rekamind-backend.exe bila ada).
   Buka lagi: rekaman muncul di "Rekaman yang belum terunggah" dengan penanda terhenti mendadak, bisa diputar, tombol Unggah berfungsi.
   10 dtk setelah mematikan paksa: TIDAK boleh ada rekamind-backend.exe yatim (`Get-Process rekamind*`).
A5 [ANDA][G5] Mulai rekam. Buka jendela app: rekaman berjalan TIDAK tampil di "belum terunggah" dan tidak ada tombol hapus aktif untuknya.
A6 [ANDA] Saat merekam, ubah zona waktu Windows ke zona lain lalu kembalikan: rekaman tidak terganggu; jam rapat di UI tetap sesuai pengaturan zona Rekamind.
A7 [ANDA] Tidur/bangunkan (sleep) laptop saat merekam 1 menit: rekaman berhenti rapi atau lanjut; tidak korup (WAV bisa diputar).
A8 [ANDA] Disk hampir penuh (opsional): pesan galat yang jelas, tidak menghapus rekaman lama.

## B. Mesin & pemrosesan
B1 [G2] Pengaturan -> Mesin transkripsi -> "Pasang untuk CPU" dari UI sampai "Uji mesin" hijau. Catat waktu & progres.
B2 [G2] Lalu "Pasang untuk NVIDIA GPU" + pemisah pembicara. Uji mesin: "GPU NVIDIA terdeteksi". `engine-pack\av-*.dist-info` = 16.x.
B3 [ANDA] Batalkan: mulai "Pasang ulang", klik "Batalkan" setelah log bergerak: berhenti < 5 dtk, tidak ada proses pip tersisa, UI normal.
B4 Isi kunci API Groq (tier gratis 8000 TPM) + token HF. Proses rapat >= 50 mnt (`recordings/042daa73...` bila ada). [G6]
   Harapan: selesai, ATAU transkrip tersimpan + banner kuning + "Buat ulang ringkasan" yang berfungsi tanpa transkripsi ulang. Catat waktu.
B5 Log harus "loading whisper ... on cuda (int8)" di GTX 1080 Ti; VRAM (nvidia-smi) puncak <= 6 GB.
B6 [ANDA] Mic nyata dengan suara: pembicara "ME" muncul, teks mikrofon benar; speaker -> SPEAKER_xx. [G15]
B7 Unduh model pertama: panel/log menampilkan ukuran terunduh bertambah tiap beberapa detik (bukan diam).
B8 [G8] Biarkan jendela terbuka 30 menit tanpa melakukan apa pun: backend.log TIDAK memuat shutdown/startup berulang; jumlah "GET /api/health" wajar (~2/menit).
B9 Tutup jendela (bukan Keluar) dan tunggu 12 menit: backend mati sendiri (hemat memori). Buka jendela: menyala lagi tanpa galat.
B10 (opsional) beban VRAM: jalankan aplikasi berat lain (~8 GB VRAM) lalu proses: tidak crash; log "out of memory ... retrying".
B11 `python -m rekamind_server.bench <wav> --model small`: jalan, peak_rss_mb > 0.

## C. Penyimpanan kredensial & pemasangan
C1 [ANDA][G9] Simpan kunci API dan token HF. Keluar total (tray -> Keluar), buka lagi: kotak bertopeng "Sudah tersimpan"; proses rapat tanpa mengetik ulang.
   Cek Credential Manager (Windows): ada entri "id.rekamind.desktop".
C2 [ANDA][G10] Uninstall: data rekaman tetap ada? (harapan: ya); tidak ada proses/ikon tray tersisa. Install ulang: rapat lama muncul lagi.
C3 [ANDA][G10] Pasang versi baru di atas versi lama (tanpa uninstall): data dan pengaturan utuh; engine-pack tetap berfungsi.
C4 Dua instance: buka app kedua: jendela pertama yang muncul (single instance), tidak ada backend ganda.
C5 [ANDA] Tray: ikon ada, klik kiri membuka jendela, menu Mulai/Hentikan/Keluar bekerja; ikon berubah merah saat merekam.
C6 [ANDA] Mulai otomatis saat login (jika fitur ada) / argumen `--hidden`: hanya tray, tanpa jendela, RAM kecil.

## D. Tab Task, ekspor, zona waktu (UI)
D1 [ANDA][G15] Rapat hasil B4 -> tab Task: konfirmasi satu, ubah PIC & tenggat, tolak satu, batalkan satu. Muat ulang: tersimpan.
D2 [ANDA] "Putar dari" pada kutipan bukti task: audio melompat ke waktu yang benar (+/- 2 dtk).
D3 [ANDA] Rapat >= 50 mnt: tab Transkrip dan Task mulus saat di-scroll; klik kalimat memutar dari sana.
D4 [ANDA][G7] Ekspor -> Word: BUKA di Microsoft Word (bukan penampil lain): tanpa peringatan "berkas rusak", judul, peserta, ringkasan,
   keputusan, tabel task, transkrip lengkap; jam tertulis "... WIB". Coba juga dibuka di LibreOffice/Google Docs bila ada.
D5 [ANDA] Ekspor Markdown: tempel ke Notion/Obsidian/GitHub: tampil rapi; teks aneh (tanda * _ # < >) tidak merusak tampilan.
D6 [ANDA] Ekspor JSON: valid (`python -m json.tool`), `schema` = rekamind.meeting/v1.
D7 [ANDA] Pengaturan -> Zona waktu: pilih WITA lalu UTC: jam di daftar rapat dan detail berubah dan menyebut zonanya; "Ikuti server" kembali WIB.
D8 [ANDA] Rapat yang direkam setelah tengah malam WIB ("besok" diucapkan pukul 00:30): tenggat = HARI WIB berikutnya (bukan hari UTC).

## E. Integrasi task (butuh akun asli)
E1 [ANDA][G11] GitHub: buat repo uji + token (fine-grained, Issues read/write). Tambah integrasi -> "Uji integrasi" harus "Terhubung ke ...".
   Konfirmasi 2 task -> Kirim: 2 issue muncul dengan judul, label, deskripsi (PIC/tenggat/estimasi/kutipan), tautan balik dari UI.
   Kirim lagi: tidak ada issue baru ("tidak berubah"). Ubah judul task -> Kirim: issue yang SAMA berubah. Hapus issue di GitHub lalu ubah & kirim: issue baru dibuat.
   Pemetaan "Budi = <username>": assignee terisi. Token salah: pesan "Token ditolak ...", token tidak muncul di pesan mana pun.
E2 [ANDA][G11] GitLab (gitlab.com atau milik sendiri): sama dengan E1; periksa due_date, assignee (ID angka), label, time estimate (estimasi 2 jam -> "2h").
   Catat bila ada field yang ditolak API (nama field/kode status): itu mengonfirmasi/menolak asumsi saya dari dokumentasi.
E3 Webhook ke penerima nyata (mis. https://webhook.site atau n8n): tanda tangan HMAC cocok dengan rumus di docs/INTEGRATIONS.md; header Idempotency-Key ada.
E4 [ANDA] Keamanan: di server bersama, URL http://127.0.0.1/... dan https://localhost/... DITOLAK dengan pesan jelas; di desktop lokal DIIZINKAN.
E5 Token tidak ada di `backend.log`, di respons API (`GET /api/integrations`), maupun di `secret.key` selain kunci (cek `findstr /s /i ghp_ %LOCALAPPDATA%\id.rekamind.desktop`).

## F. Server bersama (jika dirilis)
F1 [ANDA][G12] Google OAuth client sendiri (docs/AUTH.md): login browser dan dari app desktop (mode Server terpisah). Dua akun: tidak saling melihat rapat;
   super admin mengelola pengguna; logout mencabut sesi; REKAMIND_SECRET_KEY diisi -> integrasi tersedia; tidak diisi -> pesan alasannya.
F2 docker compose up -d --build dari `.env` (docs/INSTALL.md); healthcheck hijau; di belakang reverse proxy https; unggahan 460 MB lancar (nginx: lihat INSTALL.md).
F3 MinIO asli (REKAMIND_STORAGE=s3): unggah, putar (Range), hapus permanen -> objek hilang.
F4 Postgres: `REKAMIND_DATABASE_URL=postgresql+asyncpg://...`: migrasi otomatis, dua pengguna serentak.

## G. Linux (jika rilis Linux diklaim) [G13]
G1 [ANDA] Pasang `.deb` di Ubuntu/Debian desktop (bukan container): ikon tray, hotkey global (Wayland kadang membatasi: catat), merekam mic + audio komputer lewat PulseAudio/PipeWire.
G2 `rekamind-rec record --stats` di sana: CPU/RAM; `parec` ada? Pesan jelas bila tidak.

## H. Yang perlu diperiksa mata manusia (kualitas)
H1 [ANDA] Akurasi transkrip bahasa Indonesia pada rapat nyata Anda (large-v3 int8): layak dipakai? Contoh kesalahan yang paling mengganggu.
H2 [ANDA] Kualitas ringkasan/task dari LLM: task yang dihasilkan benar-benar ditugaskan? Ada yang mengarang? PIC dan tenggat tepat?
H3 [ANDA] Kesan UI: mana yang membingungkan (tulis apa adanya, jangan dihaluskan).

## Laporan (format wajib)
1. Tabel: butir | status | bukti (angka/pesan/berkas) | catatan.
2. GERBANG RILIS: tiap G1..G15 = LULUS/GAGAL/TIDAK DIUJI. Keputusan: GO atau NO-GO beserta alasannya.
3. Temuan baru berurutan keparahan, dengan langkah reproduksi.
4. Yang tidak bisa diuji. 5. Berkas untuk pengembang (backend.log, keluaran smoke, screenshot galat).
Simpan sebagai docs/v2/PC_FINAL_RESULTS.md; commit; push ke v2/core-api.
````

## Daftar singkat "kenapa belum yakin" (agar uji tidak terasa acak)

| Area | Belum terbukti karena |
|---|---|
| Rekam jendela tertutup ≥ 30 mnt, tanpa backend | Baru 53 dtk di Windows |
| Mati paksa / yatim / pemulihan | Dibuktikan di Linux; Windows belum |
| Hapus rekaman berjalan | Tes lulus otomatis di Windows; belum diamati manual |
| Backend menyala ulang sendiri | Penyebab diperbaiki di kode; belum diamati 30 menit di Windows |
| Pasang mesin dari UI (CPU) & batalkan | GPU lewat UI sudah; CPU dan Batalkan belum |
| Kredensial setelah keluar | Credential Manager belum pernah diuji |
| Word dibuka di Microsoft Word | Hanya dibaca ulang dengan python-docx |
| Zona waktu di UI & tenggat tengah malam | Terbukti di server/Postgres; tampilan UI Windows belum |
| GitHub/GitLab asli | Hanya server tiruan; detail API dari ingatan dokumentasi |
| Google asli, MinIO asli | Tidak terjangkau dari sandbox |
| Linux desktop sungguhan | Hanya Xvfb; tray/hotkey/audio nyata belum |
| Akurasi transkrip & kualitas LLM | Tidak ada referensi manusia |
| Penandatanganan installer | Belum ada sertifikat |
