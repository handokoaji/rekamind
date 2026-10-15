# Uji regresi CPU + NVIDIA setelah mesin Intel/AMD ditambahkan (PC Windows + GTX 1080 Ti)

Sejak uji akhir terakhir (`ebc3f1c`), kode pemasangan mesin (`server/rekamind_server/enginepack.py`) berubah untuk mendukung mesin
Intel (OpenVINO) dan AMD (Vulkan), dan pemasangan kini lebih terpantau (diagnostik, progres, peringatan macet, unduhan dapat dilanjutkan).
Uji ini memastikan **jalur CPU dan NVIDIA tidak rusak** dan menjawab mengapa pemasangan NVIDIA dari aplikasi terpasang terasa sangat lambat
(laporan: lambat dari `.exe` unduhan GitHub, lancar saat diuji dari terminal).

## Cara pakai
1. Ambil installer dari CI branch `feat/amd-vulkan`, commit `9453a3d` atau lebih baru (Actions -> run v2 CI hijau pada commit itu ->
   Artifacts -> `rekamind-installer-windows-latest`, zip berisi `.exe`).
2. Salin blok di bawah ke Claude di PC Windows + GTX 1080 Ti.
3. Hasil ditulis ke `docs/v2/NVIDIA_REGRESSION_RESULTS.md`.

````text
Kamu menguji REGRESI jalur CPU dan NVIDIA pada aplikasi "Rekamind" di PC ini (Windows + GTX 1080 Ti). Balas dalam Bahasa Indonesia.
Jujur dan berbukti: tandai tiap butir LULUS / GAGAL / TIDAK BISA DIUJI (alasan). Untuk GAGAL sertakan pesan galat persis dan 20 baris log
relevan. JANGAN mengubah kode (hanya prasyarat). JANGAN menulis rahasia (kunci API, token) di laporan. Jangan merge ke master.

## Konteks
- Repo https://github.com/handokoaji/rekamind , branch `feat/amd-vulkan`, commit `9453a3d` atau lebih baru. `git pull`.
  Baca `git log --oneline ebc3f1c..HEAD -- server/rekamind_server/enginepack.py` dan diff-nya, serta `server/tests/test_engine_regression.py`
  dan `server/tests/test_pip_progress.py` (apa yang dijanjikan tidak berubah).
- Yang berubah di jalur CPU/NVIDIA (klaim yang diuji): (1) argumen pip kini ditambah `--timeout 60 --retries 10`, dan pada pip >= 25.1 juga
  `--resume-retries 5` + `--progress-bar raw`; (2) stdout pip dibungkus agar menampilkan satu baris progres tiap 5 dtk dan peringatan bila
  tidak ada kemajuan 60 dtk; (3) log pemasangan diawali blok "Diagnostik" (versi pip, variabel pip/proxy dengan kredensial disamarkan, waktu
  DNS/TLS ke pypi.org dan files.pythonhosted.org); (4) deteksi GPU (`gpus` di `engines status`) di-cache di `gpus.json` selama 24 jam;
  (5) jenis mesin baru (Intel/AMD) hanya aktif bila dipilih; CPU/NVIDIA memakai faster-whisper seperti sebelumnya.
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (recordings\, backend\logs\backend.log, backend\engine-pack\, gpus.json).
  CLI backend terpasang (cari dengan `Get-ChildItem -Recurse -Filter rekamind-backend.exe`):
  `rekamind-backend.exe engines status|check|install cpu|install cuda|warmup <model>`.
- Fakta yang sudah diverifikasi pengelola: PyPI menyimpan wheel `nvidia-cudnn-cu12` (±743 MB) dan `nvidia-cublas-cu12` (±553 MB) untuk Windows
  di `files.pythonhosted.org` (BUKAN pypi.nvidia.com). Pemasangan NVIDIA mengunduh ±1,3 GB. Penyebab laju lambat dari `.exe` TIDAK diketahui.

## Langkah 0. Siapkan
1. Catat: `Get-CimInstance Win32_VideoController | Select Name, DriverVersion`, versi Windows, koneksi (kabel/Wi-Fi), `nvidia-smi` (driver, VRAM).
2. Pasang installer baru (di atas versi lama). `Get-Process rekamind*` tidak boleh menyisakan proses yatim.
3. Hapus `backend\engine-pack` dan `gpus.json` agar uji bersih (jangan hapus `recordings\`). Catat variabel lingkungan:
   `Get-ChildItem Env: | Where-Object Name -match 'PIP|PROXY|SSL|REQUESTS'` di terminal yang kamu pakai (catat, jangan ubah).

## BAGIAN 1. Pemasangan NVIDIA dari aplikasi (inti uji)
N1 [pasang NVIDIA dari UI]. Buka app -> Pengaturan -> Mesin transkripsi -> centang "Sertakan pemisah pembicara (pyannote)" (ini skenario yang
   sebelumnya gagal dengan `OSError: [Errno 22] Invalid argument` / kode 120 tepat saat unduhan pertama dimulai; unduhan ikut menarik PyTorch dan
   banyak paket CUDA) lalu "Pasang untuk NVIDIA GPU". Pasang TANPA pyannote hanya bila yang dengan pyannote sudah lulus.
   Catat dan SALIN ke laporan: (a) blok "Diagnostik" di awal log (semua barisnya), (b) apakah muncul baris progres `  … X / Y MB (Z%), N.NN MB/s`
   tiap ±5 dtk, (c) kecepatan rata-rata per berkas besar (cuDNN ±743 MB, cuBLAS ±553 MB), (d) apakah peringatan "Tidak ada kemajuan unduhan"
   muncul dan kapan, (e) total waktu sampai selesai atau sampai kamu hentikan (maks 40 menit; bila lebih, Batalkan dan catat), (f) ukuran
   `engine-pack` akhir. Panel TIDAK boleh hang/berkedip; konsol hitam tidak boleh muncul. Pemasangan TIDAK boleh berhenti dengan `Errno 22`,
   "Exception ignored on flushing sys.stdout", atau kode keluar 120: bila terjadi, salin 30 baris terakhir log PERSIS (itu kegagalan inti).
N2 [uji mesin]. "Uji mesin" harus: faster-whisper + "GPU NVIDIA terdeteksi: 1". CLI `engines check` -> `"ok": true`, `cuda_devices: 1`.
   `engines status` -> `kind: "cuda"`, `asr: true`, `gpus` memuat `vendor: "nvidia"` (tanpa rekomendasi AMD/Intel di panel karena NVIDIA ada).
N3 [transkripsi di GPU]. Proses rekaman Indonesia >= 3 menit. Log harus `loading whisper large-v3 on cuda (int8)` (BUKAN cpu), selesai
   benar, dan hasil setara hari sebelumnya (jumlah segmen/waktu wajar; RTF mendekati 0,008-0,02). Catat VRAM puncak (`nvidia-smi`).

## BAGIAN 2. Mengapa lambat dari .exe? (pisahkan penyebab, tanpa mengubah kode)
N4 [CLI exe vs UI]. Dari TERMINAL yang kamu klaim "lancar", jalankan exe yang SAMA dengan yang dipakai aplikasi:
   `& "<jalur>\rekamind-backend.exe" engines install cuda` setelah menghapus `engine-pack` lagi. Bandingkan dengan N1:
   blok Diagnostik (variabel pip/proxy yang terlihat berbeda?), kecepatan MB/s, total waktu. Jika CLI cepat tapi UI lambat -> penyebab di
   lingkungan peluncuran aplikasi (variabel/proxy tidak diwarisi). Jika keduanya lambat -> jaringan atau pip beku.
N5 [pip biasa]. Bandingkan dengan `pip download nvidia-cudnn-cu12==9.* --no-deps -d C:\temp\wheels --only-binary=:all:` memakai Python
   biasa (catat versi pip dan kecepatan; hanya salah satu berkas). Itu pembanding murni jaringan.
N6 [waktu uji]. Ulangi pengukuran N1/N4 sekali di jam berbeda bila ada indikasi jaringan berubah-ubah; catat jamnya.
N7 [lanjut unduhan]. Mulai pemasangan NVIDIA, tunggu cuDNN > 20%, klik Batalkan, lalu pasang ulang: apakah progres MULAI DARI AWAL atau
   melanjutkan? (pip >= 25.1 punya `--resume-retries`; pembatalan oleh Batalkan membunuh proses sehingga mungkin mulai dari awal: laporkan fakta).
   Catat juga: berhenti < 5 dtk setelah Batalkan, tidak ada sisa proses `rekamind-backend`/`pip` yatim, tidak ada berkas `*.part` tertinggal.

## BAGIAN 3. Jalur CPU dan regresi lain
N8 [pasang CPU]. Hapus `engine-pack`, pasang "CPU" dari UI: selesai tanpa galat, `engines status` -> `kind: "cpu"`; "Uji mesin" OK (GPU NVIDIA
   tidak dipakai/terdeteksi untuk jenis ini tidak apa-apa); proses rekaman pendek: log `on cpu` dan hasil benar.
N9 [pindah balik]. Pasang NVIDIA lagi (cache pip mungkin mempercepat): `kind: "cuda"` kembali dan transkripsi di cuda lagi.
N10 [cepat]. `engines status` kedua kalinya harus cepat (deteksi GPU di-cache: ukur dengan `Measure-Command`, harapan < 2 dtk) dan `gpus.json` ada.
N11 [tombol baru tidak mengganggu]. Panel menampilkan tombol "Pasang untuk Intel GPU" dan "Pasang untuk GPU AMD (Vulkan)" di PC ini:
   JANGAN diklik. Pastikan tidak ada kalimat rekomendasi "GPU Intel/AMD terdeteksi" (PC ini NVIDIA saja; bila iGPU Intel ada di CPU-nya,
   notifikasi Intel boleh muncul hanya bila NVIDIA tidak terdeteksi: catat apa yang tampil).
N12 [regresi cepat]. Rekam 2 menit lewat app, proses dengan mesin NVIDIA, ekspor Word/Markdown, ganti bahasa antarmuka ID/EN.
N13 [stabilitas]. Idle 15 menit: backend tidak restart berulang, tidak ada proses yatim, memori kembali normal.

## Bukti yang harus dilampirkan
Blok Diagnostik lengkap (N1 dan N4), 10-15 baris progres, `engines status` dan `engines check` (JSON), kutipan `backend.log` untuk N3/N8,
versi pip yang dipakai aplikasi, ukuran `engine-pack`, `nvidia-smi`, hasil `Measure-Command`.
Untuk setiap GAGAL: galat persis, perintah, dugaan penyebab (label [Medium]/[Low]) tanpa mengubah kode.

## Laporan
Tulis `docs/v2/NVIDIA_REGRESSION_RESULTS.md`: tabel N1-N13 (status + bukti singkat), jawaban atas pertanyaan "mengapa lambat dari .exe"
(fakta N4/N5, bukan dugaan), temuan berurutan keparahan, dan keputusan:
- **GO**: N1-N3 dan N8-N9 LULUS (CPU dan NVIDIA tidak rusak) -> boleh merge ke master dan rilis beta.2.
- **NO-GO**: sebut butir penghalang.
Commit HANYA berkas laporan ke branch `feat/amd-vulkan` (`git pull --no-rebase` bila ditolak; jangan rebase/force), `git push`. Jangan PR.
````

## Cara membaca hasilnya (untuk pengembang)

| Hasil | Arti / tindakan |
|---|---|
| CLI exe cepat, UI lambat | Lingkungan peluncuran: aplikasi tidak mewarisi variabel/proxy; tambahkan pengaturan proxy/mirror di UI |
| Keduanya lambat, `pip download` biasa cepat | Ada yang beda pada pip beku (TLS, proxy, IPv6); bandingkan blok Diagnostik |
| Semua lambat | Jaringan/CDN; dokumentasi + pasang offline (`PIP_FIND_LINKS`) sudah ada |
| N7 mulai dari nol | Wajar bila proses dibunuh; pertimbangkan jeda "Jeda/Lanjut" atau cache wheel lebih agresif |
| N3/N8 gagal | Regresi sungguhan di jalur CPU/NVIDIA: prioritas tertinggi, perbaiki sebelum merge |
