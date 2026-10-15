# Uji GPU AMD terintegrasi (Vulkan / whisper.cpp) di PC AMD

Untuk fitur eksperimental di branch `feat/amd-vulkan` (belum di `master`, tidak ada di rilis beta.1).
Target pertama: laptop **Ryzen AI 7 350** (iGPU Radeon 860M), Windows 11. Jalurnya generik untuk iGPU Radeon
RDNA2/3/3.5 (680M, 780M, 860M: Ryzen 7 7735HS, 8845HS, dan setara) dan GPU lain yang punya driver Vulkan, tetapi **hanya
perangkat yang benar-benar diuji yang boleh diklaim berfungsi**. Semua kode baru teruji hanya dengan program tiruan di
sandbox; program `whisper-cli` Vulkan asli dibangun oleh CI dan baru dijalankan pada perangkat keras ini.

Butir **[ANDA]** butuh mata/telinga/tangan pengguna (mis. grafik GPU); minta pengguna lalu tunggu.

## Prasyarat (dikerjakan pengelola sebelum uji)
1. (Sudah dipenuhi pada 2026-10-15: whisper.cpp v1.9.5, Windows + Linux, SHA-256 di `manifest.json`.) Workflow **Engine assets (whisper.cpp Vulkan)** sudah dijalankan dan rilis `engine-assets` memuat
   `whisper-cli-vulkan-windows-x64.zip` + `manifest.json`. Tanpa itu pemasangan GAGAL dengan "Tidak bisa mengambil daftar mesin".
   Periksa: https://github.com/handokoaji/rekamind/releases/tag/engine-assets
2. Installer dari CI branch `feat/amd-vulkan` (Actions -> run terbaru hijau -> Artifacts -> `rekamind-installer-windows-latest`).

````text
Kamu menguji fitur EKSPERIMENTAL "GPU AMD (Vulkan)" pada aplikasi Rekamind di PC ini. Balas dalam Bahasa Indonesia.
Jujur dan berbukti: tandai tiap butir LULUS / GAGAL / TIDAK BISA DIUJI (alasan). Untuk GAGAL sertakan pesan galat persis
dan 20 baris log relevan. JANGAN memperbaiki atau mengubah kode (hanya prasyarat seperti Git atau driver boleh dipasang).
JANGAN menulis rahasia (kunci API, token) di laporan. Jangan merge ke master.

## Konteks
- Repo https://github.com/handokoaji/rekamind , branch `feat/amd-vulkan`, commit terbaru. `git pull`. Baca `README.md`
  ("GPU support"), `docs/INSTALL.md`, dan kode: `server/rekamind_server/engine_assets.py`,
  `server/rekamind_server/engines/whispercpp.py`, `server/rekamind_server/enginepack.py` (cari "vulkan"),
  `.github/workflows/engine-assets.yml`.
- Cara kerja yang diklaim: jenis mesin "vulkan" mengunduh `whisper-cli` (whisper.cpp v1.9.5 + Vulkan, dibangun CI) ke
  `engine-pack\whispercpp\`, memeriksa SHA-256 terhadap `manifest.json`. Model ggml (large-v3 q5_0, ±1 GB, dari Hugging Face)
  disimpan di `whispercpp-models\` folder data. Transkripsi menjalankan `whisper-cli` sebagai proses terpisah dengan `-dev 0`;
  perangkat dibaca dari log "ggml_vulkan: 0 = ...". Bila Vulkan tidak terinisialisasi, whisper.cpp jatuh ke CPU (harus terlihat
  di log sebagai peringatan). Pemisahan pembicara (pyannote) opsional. Glosarium tidak diterapkan.
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (recordings\, backend\logs\backend.log, backend\engine-pack\).
  CLI backend terpasang (cari dengan `Get-ChildItem -Recurse -Filter rekamind-backend.exe`):
  `rekamind-backend.exe engines status|check|warmup <model>|install vulkan`.
- PC ini kemungkinan punya iGPU Radeon 860M saja (tanpa GPU diskrit). Bila ada GPU kedua, catat dan uji `-dev` keduanya.

## Langkah 0. Catat perangkat dan pasang bersih
1. `Get-CimInstance Win32_VideoController | Select Name, DriverVersion, AdapterRAM`, `systeminfo | findstr /C:"Total Physical Memory"`,
   versi Windows, mode daya (colok listrik, kinerja tinggi). Catat versi driver AMD Adrenalin. Jalankan `vulkaninfo --summary`
   bila tersedia (Vulkan SDK/`vulkan-tools`); bila tidak ada, catat itu.
2. Pasang installer (di atas versi lama boleh). `Get-Process rekamind*` tidak boleh menyisakan proses yatim.
3. Uji bersih: hapus `backend\engine-pack` dan `whispercpp-models` (jangan hapus `recordings\`).

## BAGIAN 1. Gerbang wajib (urutan penting)

A1 [deteksi GPU]. Pengaturan -> Mesin transkripsi harus menampilkan "GPU AMD terdeteksi di komputer ini..." dan tombol
   "Pasang untuk GPU AMD (Vulkan)". CLI `engines status` -> `"gpus"` memuat `vendor: "amd"` (catat `name`). Ukur latensi pemanggilan
   kedua (harus cepat; deteksi di-cache 24 jam di `gpus.json`).

A2 [pasang program]. Klik "Pasang untuk GPU AMD (Vulkan)" (tanpa pemisah pembicara). Catat: progres, total waktu, ukuran
   `engine-pack\whispercpp`, galat? Yang harus terbukti: manifest terambil, SHA-256 cocok, `whisper-cli.exe` ada.
   Uji juga keamanan dasar: SmartScreen/antivirus memblokir `whisper-cli.exe`? (program belum bertanda tangan). Uji Batalkan sekali (< 5 dtk)
   lalu pasang penuh. Periksa `engines status` -> `kind: "vulkan"`, `asr: true`.

A3 [program berjalan]. `Uji mesin` (UI) dan CLI `engines check`: `"ok": true`, `"whispercpp": "v1.9.5"`, dan sebelum ada model muncul
   "Program terpasang; unduh model dulu...". Jika `ok:false` (mis. kode 0xC0000135 = DLL hilang, Vulkan tidak ada): salin JSON dan
   periksa apakah `vulkan-1.dll` ada di `C:\Windows\System32` (driver Adrenalin memasangnya).

A4 [unduh model]. "Unduh model large-v3 sekarang" (atau `engines warmup large-v3`). Catat waktu, ukuran file di `whispercpp-models\`
   (diharapkan `ggml-large-v3-q5_0.bin` ±1,1 GB; bila `ggml-large-v3.bin` ±3 GB berarti varian terkuantisasi tidak ada: temuan).

A5 [GPU benar-benar dipakai]. `Uji mesin` lagi: harus "GPU terdeteksi: AMD Radeon(TM) 860M Graphics" (atau serupa; catat teks persisnya).
   Bila tertulis "Tidak ada perangkat Vulkan; memakai CPU": temuan penting. Uji manual (tanpa mengubah kode):
   `whisper-cli.exe -m <model> -f <wav 3 dtk> -l id -dev 0` dan salin baris `ggml_vulkan:` dari stderr.

A6 [transkripsi nyata]. Rekaman Indonesia >= 3 menit, >= 2 pembicara. Proses lewat UI. Catat: selesai/gagal; waktu proses vs durasi
   audio (RTF); log backend harus memuat "whisper.cpp memakai GPU Vulkan: <nama>" (BUKAN "berjalan di CPU"). [ANDA] amati Task Manager ->
   Kinerja -> GPU: engine Compute/3D/Copy dan "Memori GPU bersama" naik saat proses? Catat angka. Penggunaan CPU saat itu?

A7 [kualitas]. Untuk rekaman SAMA bandingkan dengan CPU (pasang "CPU" lewat UI lalu proses ulang): teks Indonesia benar/stabil,
   halusinasi pada bagian hening ("terima kasih telah menonton", ulang frasa), potongan 3-5 kalimat berdampingan, jumlah segmen dan
   granularitas timestamp (whisper.cpp memberi segmen per kalimat), pembagian pembicara, waktu CPU vs GPU. Laporkan fakta terpisah dari
   penilaian subjektif. Bandingkan juga model q5_0 vs `large-v3-turbo` bila sempat (Pengaturan -> model Whisper = large-v3-turbo).

A8 [rapat panjang]. Rapat >= 30 menit: selesai? waktu, puncak memori (`Get-Process whisper-cli` PeakWorkingSet), suhu/kipas [ANDA],
   iGPU berbagi RAM: apakah sistem jadi lambat/tidak responsif saat proses? Tandai TIDAK BISA DIUJI bila tak ada rekaman.

## BAGIAN 2. Sekitar fitur
A9 [pindah mesin]. Pasang "CPU", lalu "Vulkan" lagi, lalu (bila mau) Intel/NVIDIA hanya jika perangkat ada: `engines status` berganti
   `kind` sesuai, transkripsi memakai mesin yang benar (log), dan tidak ada sisa yang merusak. CPU harus tetap berfungsi penuh.
A10 [offline/galat jaringan]. Putuskan internet lalu coba pasang/unduh model: pesan galat harus jelas, tidak ada berkas setengah jadi
    (`*.part` bersih), dan aplikasi tetap bisa merekam dan memakai mesin CPU.
A11 [checksum]. (Opsional, tanpa mengubah kode) Ubah satu byte pada zip yang diunduh tidak praktis; cukup catat bahwa `manifest.json`
    memuat `sha256` dan log pemasangan menampilkan 12 karakter pertamanya.
A12 [stabilitas]. Idle 15 menit setelah proses: backend tidak restart berulang, tidak ada proses `whisper-cli` yatim, memori kembali normal.
A13 [regresi]. Rekam 2 menit lewat app, proses dengan mesin Vulkan, ekspor Word/Markdown, ganti bahasa antarmuka ID/EN.

## Bukti yang harus dilampirkan
`engines status`, `engines check`, baris `ggml_vulkan:` dari log, kutipan `backend.log` untuk A6, ukuran folder/berkas, nama GPU/driver,
RAM, versi Windows, dan BUILD_INFO.json di `engine-pack\whispercpp\`. Untuk setiap GAGAL: galat persis, perintah, dugaan penyebab (label
[Medium]/[Low]) tanpa mengubah kode.

## Laporan
Tulis `docs/v2/AMD_GPU_RESULTS.md`: tabel A1-A13 (status + bukti singkat), temuan berurutan keparahan (gagal pasang/jalan > hasil salah >
kualitas/kecepatan > kosmetik), dan keputusan **GO eksperimental** (A1-A6 LULUS dan A7 tanpa teks rusak) atau **NO-GO** (sebut penghalang).
Commit HANYA berkas laporan ke branch `feat/amd-vulkan` (`git pull --no-rebase` bila ditolak; jangan rebase/force), `git push`. Jangan PR.
````

## Tindak lanjut untuk pengembang

| Temuan | Kemungkinan tindakan |
|---|---|
| `ok:false`, DLL hilang | Tautkan runtime statis di CI (`CMAKE_MSVC_RUNTIME_LIBRARY`), atau sertakan DLL yang kurang |
| `Tidak ada perangkat Vulkan` | Periksa urutan perangkat (`-dev`), pesan driver; fallback ke Intel/CPU yang jelas di UI |
| Varian q5_0 tidak ada / lambat | Ganti default kuantisasi atau model (turbo) |
| Halusinasi pada hening | Aktifkan VAD whisper.cpp (`--vad` + model Silero) |
| SmartScreen memblokir `whisper-cli.exe` | Tanda tangan kode / dokumentasi pengecualian |
