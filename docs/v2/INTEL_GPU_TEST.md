# Uji Intel GPU terintegrasi (OpenVINO) di PC Intel

Untuk fitur eksperimental di branch `feat/intel-gpu` (belum di `master`, tidak ada di rilis beta.1).
Target perangkat: laptop **Intel Core Ultra 7 155H** (iGPU Intel Arc), Windows 11. Hasil rancangan ini hanya teruji
dengan tiruan di sandbox; runtime OpenVINO + `optimum-intel` asli belum pernah dijalankan oleh v2. Tujuan uji:
membuktikan atau membantah, dengan bukti, bahwa jalur ini bekerja pada perangkat keras nyata.

Butir **[ANDA]** butuh mata/telinga/tangan pengguna (mis. melihat grafik GPU); minta pengguna lalu tunggu.

## Cara pakai

1. Pasang installer dari CI branch `feat/intel-gpu` (**disarankan**) atau bangun sendiri:
   - CI: https://github.com/handokoaji/rekamind/actions (run terbaru branch `feat/intel-gpu`, hijau) → Artifacts →
     `rekamind-installer-windows-latest` (zip berisi `.exe`). Perlu login GitHub.
   - Bangun: `git pull`, `pip install -e "server[dev]" pyinstaller`, `python scripts/build_desktop.py`.
2. Salin blok di bawah ke Claude di PC Intel itu.
3. Hasil ditulis ke `docs/v2/INTEL_GPU_RESULTS.md`.

````text
Kamu menguji fitur EKSPERIMENTAL "Intel GPU (OpenVINO)" pada aplikasi Rekamind di PC ini. Balas dalam Bahasa Indonesia.
Jujur dan berbukti: tandai tiap butir LULUS / GAGAL / TIDAK BISA DIUJI (alasan). Untuk GAGAL sertakan pesan galat persis
dan 20 baris log relevan. JANGAN memperbaiki atau mengubah kode (satu-satunya yang boleh dipasang: prasyarat seperti
Git, driver). JANGAN menulis rahasia (kunci API, token) di laporan. Jangan merge ke master.

## Konteks
- Repo https://github.com/handokoaji/rekamind , branch `feat/intel-gpu`, commit `d5bab82` atau lebih baru.
  `git pull`. Baca `README.md` bagian "GPU support", `docs/INSTALL.md`, dan kode:
  `server/rekamind_server/engines/openvino.py`, `server/rekamind_server/enginepack.py` (cari "openvino"),
  `server/rekamind_server/engines/registry.py` (`use_openvino`).
- Cara kerja yang diklaim: jenis mesin "openvino" dipasang ke `engine-pack` (openvino + optimum-intel + torch CPU).
  Model Whisper dikonversi sekali ke OpenVINO IR (di-cache `openvino-models\` di folder data backend), lalu dijalankan di
  perangkat OpenVINO "GPU" (iGPU Intel); bila GPU gagal memuat model otomatis turun ke "CPU". Audio dipotong jendela 30 dtk;
  timestamp per segmen dipakai bila `optimum-intel` mendukung `return_timestamps`, kalau tidak satu segmen per jendela.
  Jendela hening dilewati. Glosarium tidak diterapkan di mesin ini.
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (recordings\, backend\logs\backend.log, backend\engine-pack\).
  Perintah CLI backend terpasang (cari lokasi persisnya dengan `Get-ChildItem -Recurse -Filter rekamind-backend.exe`):
  `rekamind-backend.exe engines status|check|warmup <model>|install openvino`.
- Pengguna sebelumnya memvalidasi jalur OpenVINO GPU v1 (aplikasi lama) di mesin ini: transkripsi Indonesia benar dan
  stabil; NPU gagal (jangan diuji).

## Langkah 0. Catat perangkat dan pasang bersih
1. Catat: `Get-CimInstance Win32_VideoController | Select Name, DriverVersion, AdapterRAM`, `systeminfo | findstr /C:"Total Physical Memory"`,
   versi Windows, daya (colok listrik, mode kinerja). Catat versi driver Intel Graphics.
2. Pasang installer (di atas versi lama boleh). Pastikan tidak ada proses `rekamind*` yatim: `Get-Process rekamind*`.
3. Untuk uji bersih: tutup app, hapus folder `backend\engine-pack` dan `backend\openvino-models` (bila ada). Jangan hapus `recordings\`.
4. Buka app. Catat versi (Pengaturan/judul) dan commit bila tampil.

## BAGIAN 1. Gerbang wajib (urutan penting)

I1 [deteksi GPU]. Buka Pengaturan -> Mesin transkripsi. Harus tampil kalimat "GPU Intel terdeteksi di komputer ini..." dan tombol
   "Pasang untuk Intel GPU". CLI: `rekamind-backend.exe engines status` -> JSON memuat `"gpus"` dengan entri `vendor: "intel"`
   (catat `name`; di mesin dengan GPU lain mungkin ada entri lain). Ukur latensi perintah (`Measure-Command`); bila > 3 dtk catat.
   Bila notifikasi tidak muncul tapi iGPU ada: itu temuan (sertakan keluaran `Get-CimInstance Win32_VideoController`).

I2 [pasang mesin dari UI]. Klik "Pasang untuk Intel GPU" (tanpa pemisah pembicara dulu). Catat: progres tampil dan bergerak?
   total waktu, ukuran folder `engine-pack`, galat jalur panjang/antivirus/izin?, apakah Batalkan menghentikan < 5 dtk (uji sekali,
   lalu pasang ulang penuh). Setelah selesai catat versi paket terpasang:
   `"<python backend>" -m pip list --path "<engine-pack>"` (atau lihat `*.dist-info`): openvino, openvino-genai bila ada,
   optimum, optimum-intel, transformers, torch (harus varian CPU), numpy, av (harus 16.x).
   Jika pip gagal menyelesaikan versi (konflik torch/transformers/optimum-intel) itu temuan PENTING: salin galat lengkap.

I3 [uji mesin]. Klik "Uji mesin" di UI dan jalankan CLI `rekamind-backend.exe engines check`. Yang diharapkan:
   `"ok": true`, `"openvino": "<versi>"`, `"ov_devices"` memuat `"GPU"` (mis. ["CPU","GPU","NPU"]), `"intel_gpu": true`.
   Tempel JSON-nya. Jika `ov_devices` tidak memuat GPU: catat versi driver, lalu coba (tanpa mengubah kode)
   `python -c "import openvino as ov; c=ov.Core(); print(c.available_devices); print(c.get_property('GPU','FULL_DEVICE_NAME'))"`
   dengan `PYTHONPATH=<engine-pack>`; laporkan hasilnya.

I4 [konversi model]. Klik "Unduh model large-v3 sekarang" (atau `engines warmup large-v3`). Catat: progres/log, total waktu,
   PUNCAK memori (`Get-Process rekamind-backend | select PeakWorkingSet64` atau Task Manager; PC punya berapa GB?),
   ukuran folder `openvino-models\...-ov`, apakah berhasil sampai "Model siap". Jika gagal karena memori: ulangi dengan model
   `small` (Pengaturan -> model Whisper = small, lalu warmup) dan laporkan keduanya.

I5 [transkripsi nyata di iGPU]. Siapkan rekaman berbahasa Indonesia >= 3 menit dengan >= 2 pembicara (rekam sendiri lewat app,
   atau pakai rekaman lama di `recordings\`). Proses lewat UI. Catat: selesai atau gagal; durasi proses vs durasi audio (RTF);
   di `backend.log` cari baris: `loading whisper <model> on OpenVINO GPU` (BUKAN "could not load the model" yang diikuti
   `on OpenVINO CPU` = fallback ke CPU, itu temuan), dan apakah muncul `generate(return_timestamps=True) unavailable`
   (artinya mode satu-segmen-per-30-dtk dipakai). [ANDA] amati Task Manager -> Kinerja -> GPU: apakah "GPU 0 (Intel Arc)" /
   engine Compute/3D terpakai saat proses? Catat tangkapan (angka %), dan penggunaan CPU saat itu.

I6 [kualitas]. Untuk rekaman I5 yang SAMA, bandingkan dengan mesin CPU (pasang "CPU" via UI lalu proses ulang; atau pakai
   hasil CPU yang sudah ada): (a) apakah teks Indonesia benar dan stabil (ulang frasa, melantur ke bahasa Inggris, "terima kasih
   telah menonton" di bagian hening)? (b) potongan 3-5 kalimat dari keduanya berdampingan; (c) jumlah segmen dan apakah
   timestamp segmen halus (per kalimat) atau kasar (per 30 dtk); (d) pembagian pembicara masuk akal? (e) waktu proses CPU vs iGPU.
   Jangan menilai berlebihan: laporkan fakta dan beri penilaian subjektif terpisah.

I7 [rapat panjang]. Proses rapat >= 30 menit (gabungkan rekaman bila perlu). Catat: selesai?, waktu, puncak memori, suhu/kipas
   [ANDA] bila terasa, ada penurunan kecepatan di akhir? Jika tidak ada rekaman 30 menit, tandai TIDAK BISA DIUJI.

## BAGIAN 2. Perilaku di sekitarnya

I8 [fallback CPU]. Jalankan backend manual dengan `REKAMIND_WHISPER_DEVICE=intel` dan `REKAMIND_OPENVINO_DEVICE=CPU`
   (variabel lingkungan pada proses backend; nama variabelnya ada di `server/rekamind_server/config.py`, awalan `REKAMIND_`) lalu proses rekaman pendek: log harus "on OpenVINO CPU" dan hasil benar.
   Opsional: `REKAMIND_OPENVINO_DEVICE=NPU` (sengaja salah) -> harus jatuh ke CPU, bukan crash. Tidak bisa? tandai.

I9 [pindah jenis mesin]. Setelah I5, pasang "CPU" lewat UI: `engines status` -> `kind: "cpu"`, transkripsi memakai faster-whisper
   lagi (log "loading whisper ... on cpu"). Lalu pasang "Intel GPU" lagi: kembali `kind: "openvino"`. Catat sisa paket tak terpakai
   (ukuran `engine-pack` membengkak?) dan apakah satu jenis merusak yang lain.

I10 [stabilitas]. Biarkan app idle 15 menit setelah proses selesai: backend tidak restart berulang (0 "Started server process"
   baru), memori turun (model dilepas), `GET /api/health` wajar.

I11 [regresi cepat]. Rekam 2 menit lewat app (mikrofon + suara sistem), stop, proses dengan mesin Intel: hasil ada; ekspor
   Word/Markdown tetap berfungsi; ganti bahasa antarmuka ID/EN tetap berfungsi.

## Bukti yang harus dilampirkan
- Keluaran: `engines status`, `engines check`, daftar paket (`pip list --path`), kutipan `backend.log` untuk I5/I8, ukuran folder.
- Nama GPU/driver, RAM, versi Windows. Nomor versi paket OpenVINO/optimum-intel/transformers/torch.
- Untuk setiap GAGAL: galat persis, perintah, dugaan penyebab (diberi label [Medium]/[Low] keyakinan) tanpa mengubah kode.

## Laporan
Tulis `docs/v2/INTEL_GPU_RESULTS.md` dengan tabel butir I1-I11 (status + bukti singkat), ringkasan temuan berurutan keparahan
(GAGAL pasang/muat > hasil salah > kualitas/kecepatan > kosmetik), dan keputusan:
- **GO eksperimental**: I1-I5 LULUS dan I6 tidak menunjukkan teks rusak/halusinasi parah.
- **NO-GO**: sebutkan butir penghalang.
Lalu commit HANYA berkas laporan itu ke branch `feat/intel-gpu`, `git pull --no-rebase` bila ditolak (jangan rebase/force),
`git push`. Jangan membuat PR.
````

## Yang diharapkan dari hasilnya (untuk pengembang)

| Temuan | Kemungkinan tindak lanjut |
|---|---|
| pip gagal menyelesaikan versi | Pin versi `openvino` / `optimum-intel` / `transformers` di `PACKAGES["openvino"]` |
| `ov_devices` tanpa `GPU` | Petunjuk driver di UI; bukan bug kode |
| `return_timestamps` tidak didukung | Pakai segmentasi sendiri (VAD ringan) agar pembagian pembicara tidak kasar |
| Konversi `large-v3` kehabisan memori | Kompresi bobot int8 (`load_in_8bit`) atau default model `medium` untuk Intel |
| Hasil halusinasi/berulang | Atur ambang hening, `no_repeat_ngram_size`, atau beam search |
| Lambat (RTF mendekati CPU) | Periksa apakah benar jalan di GPU (Task Manager) dan ukuran jendela/batch |
