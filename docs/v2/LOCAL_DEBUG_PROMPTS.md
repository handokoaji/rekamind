# Prompt sesi lokal: jalankan aplikasi, reproduksi, lalu perbaiki (NVIDIA dan Intel)

Dua prompt di bawah dipakai di **sesi Claude Code lokal** pada PC yang bersangkutan (bukan di sesi cloud). Sesi lokal menjalankan aplikasinya
sendiri, mereproduksi masalah, memperbaiki kodenya di tempat, dan mengujinya di perangkat keras nyata.

## Gejala yang sedang diburu (berlaku untuk kedua PC)
- Rekaman rapat 10 menit di NVIDIA dan di Intel sama-sama berakhir dengan pesan **"Tidak ada ucapan terdeteksi dalam rekaman ini, jadi ringkasan
  dan task tidak dibuat."** Artinya hasil transkripsi kosong (`server/rekamind_server/pipeline.py`, sekitar baris 108), terjadi sebelum
  pemisah pembicara dipakai.
- `speaker.wav` terdengar **patah-patah** saat diputar langsung. Belum diketahui apakah `mic.wav` juga begitu.
- Hasil kosong yang sama di dua mesin berbeda mengarah ke audio atau perekam sebagai faktor bersama. Ini dugaan, belum terbukti.
- Pemutar di aplikasi hanya muncul bila stempel waktu di transkrip diklik, jadi pada transkrip kosong tidak ada cara memutar rekaman dari UI.
  Dengarkan langsung berkasnya.
- Intel: pemasangan OpenVINO berhasil, tetapi saat mengonversi `openai/whisper-large-v3` muncul peringatan
  `You are using a model of type whisper to instantiate a model of type fun_asr`. Belum diketahui apakah itu fatal.
- NVIDIA: pemasangan dengan build lama gagal dengan `OSError: [Errno 22]` / kode keluar 120. Penyebabnya sudah direproduksi di CI Windows
  (skenario pembaca pipa yang menutup), dan build baru lulus smoke yang sama. Belum diuji di PC nyata.

## Cara pakai
1. Di PC target: `git pull` pada branch `feat/amd-vulkan`, atau pasang installer dari run **v2 CI** hijau terbaru di branch itu
   (artefak `rekamind-installer-windows-latest`).
2. Salin blok prompt yang sesuai ke sesi Claude Code lokal, dengan direktori kerja di folder repo.
3. Hasil akhir ditulis oleh sesi lokal ke `docs/v2/LOCAL_DEBUG_NVIDIA_RESULTS.md` atau `docs/v2/LOCAL_DEBUG_INTEL_RESULTS.md`.

---

## Prompt 1. PC NVIDIA

````text
Kamu bekerja di PC Windows dengan GPU NVIDIA pada aplikasi "Rekamind" (repo ini, branch `feat/amd-vulkan`). Balas dalam Bahasa Indonesia.
Tugasmu: JALANKAN aplikasinya, REPRODUKSI masalah di bawah, cari akar masalahnya dengan bukti, PERBAIKI kodenya di sesi ini, lalu uji ulang.

## Aturan
- Jujur dan berbukti. Pisahkan "terbukti (ada keluaran/ukuran)" dari "dugaan". Beri label [High/Medium/Low confidence] pada klaim penting.
- Jangan menulis rahasia (kunci API, token HF, token login) di laporan atau commit. Jangan mengarang nilai; kalau tidak bisa diukur, tulis TIDAK DIUKUR.
- Jangan skip/matikan tes untuk membuat hijau. Jangan merge ke master, jangan buat PR. Kerjakan di branch `feat/amd-vulkan`
  (atau cabang baru darinya), commit kecil dengan pesan jelas, push hanya setelah tes lulus.
- Sebelum mengubah kode perekam atau pipeline, tulis dulu hipotesisnya dan cara membuktikannya. Jangan menebak-nebak perbaikan.
- Jangan sentuh jalur Intel/AMD kecuali perlu. Jalur CPU dan NVIDIA tidak boleh rusak: jalankan `pytest server` sebelum push.

## Masalah
1. Rekaman 10 menit menghasilkan "Tidak ada ucapan terdeteksi dalam rekaman ini..." (transkrip kosong) di mesin NVIDIA.
2. `speaker.wav` hasil rekaman terdengar patah-patah. Belum diketahui apakah `mic.wav` juga.
3. Pemasangan mesin NVIDIA dari installer lama gagal `Errno 22` / kode 120. Perlu dibuktikan sudah beres di PC ini.

## Konteks kode
- Perekam: `recorder/src/backend/wasapi_backend.rs` (loopback WASAPI untuk speaker, polling 100 ms, `autoconvert` ke 16 kHz mono PCM16, jalur cadangan
  `Convert::Soft`), `recorder/src/timeline.rs` (`Pacer`: menyisipkan nol bila dianggap tertinggal dari jam dinding, ambang `MIN_GAP_MS = 120`),
  `recorder/src/sink.rs`, `recorder/src/session.rs`, `recorder/src/resample.rs`. CLI: `rekamind-rec record` (lihat `recorder/src/main.rs`).
  Opsi `--stats` hanya mengukur CPU/memori, BUKAN putusnya audio.
- Pipeline: `server/rekamind_server/pipeline.py` (`_transcribe_and_store`; hasil ASR kosong -> catatan "Tidak ada ucapan terdeteksi"),
  mesin faster-whisper di `server/rekamind_server/engines/`. Periksa parameter VAD (penyaring non-ucapan) yang dipakai dan apakah audio patah-patah
  bisa tersaring seluruhnya.
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (`recordings\`, `backend\recordings\<id>\mic.wav|speaker.wav`, `backend\logs\backend.log`,
  `backend\engine-pack\`). Folder `AppData` tersembunyi; verifikasi sendiri lokasi persisnya.
- Bangun/jalankan lokal: lihat README bagian "For developers" (`pip install -e "server[dev]"`, `cd web && npm ci`, `python scripts/build_desktop.py`).
  Kamu boleh menjalankan backend dan antarmuka dari kode (dev) atau memasang installer; catat mana yang dipakai.

## Langkah 0. Siapkan
- Catat: `nvidia-smi` (driver, VRAM), `Get-CimInstance Win32_VideoController | Select Name, DriverVersion`, versi Windows, perangkat keluaran audio
  default (nama persis, jenisnya: speaker laptop / USB / Bluetooth / HDMI / virtual) dan perangkat mikrofon default.
- `git log --oneline -5` dan commit yang dipakai. Jika memakai installer, baris pertama log pemasangan harus `Rekamind <versi>, build <sha>`;
  `<sha>` BUKAN `8fe8a93` (itu build lama yang bermasalah).

## Bagian A. Pemasangan NVIDIA
A1. Pengaturan -> Mesin transkripsi -> NVIDIA, centang pemisah pembicara (pyannote), pasang. Catat: lulus atau tidak, total waktu, baris
    `Errno 22` / kode 120 bila ada (salin 30 baris terakhir log persis).
A2. "Uji mesin" harus melaporkan GPU NVIDIA terdeteksi. `rekamind-backend.exe engines status` -> `kind: "cuda"`.

## Bagian B. Pisahkan mesin dari perekam (inti)
B1. Buat/ambil satu WAV ucapan Indonesia yang JELAS, mono 16 kHz (mis. bacakan 1-2 menit, atau pakai TTS Windows). Simpan di folder sementara
    di luar repo. Putar sendiri dan pastikan jelas.
B2. Unggah WAV itu sebagai rapat (atau panggil mesin langsung lewat `python -m rekamind_server.bench <wav> --model large-v3 --device auto`;
    cek `--help` untuk opsi yang tersedia). Hasil: ada transkrip yang benar? Ini membuktikan mesin NVIDIA sehat TANPA perekam.
    - Jika B2 menghasilkan teks: mesin sehat, masalah ada di perekaman. Lanjut Bagian C.
    - Jika B2 kosong/salah: masalah di mesin atau VAD. Telusuri `engines/` dan parameter VAD, perbaiki, ulangi B2.

## Bagian C. Rekaman patah-patah
C1. Rekam 2 menit lewat aplikasi (atau `rekamind-rec record --out <folder sementara>`) sambil memutar ucapan yang jelas dari speaker dan berbicara
    ke mikrofon. Jangan pakai rekaman 10 menit dulu.
C2. Analisis `mic.wav` dan `speaker.wav` dengan skrip Python (`python -I`, simpan skrip di luar repo): durasi vs durasi sebenarnya, jumlah run nol
    persis (berurutan) > 20 ms, total detik nol, RMS per detik, persentase detik yang senyap. Bandingkan mic vs speaker. Jangan hanya mendengar;
    tulis angkanya.
C3. Tambahkan penghitung diagnostik sementara/permanen di perekam (jumlah penyisipan senyap `pacer`, total sampel yang disisipkan, selisih jam
    perangkat vs jam dinding, apakah jalur `Convert::Native` atau `Convert::Soft` yang dipakai, flag paket `AUDCLNT_BUFFERFLAGS_*`
    seperti DATA_DISCONTINUITY / SILENT / TIMESTAMP_ERROR bila dapat dibaca dari crate `wasapi`). Catat ke log. Jalankan ulang C1-C2.
C4. Bandingkan variabel satu per satu (satu perubahan per percobaan): speaker bawaan vs headset USB vs Bluetooth vs HDMI; aplikasi audio lain
    (browser vs pemutar lokal); `POLL` 100 ms vs 10 ms; tanpa pacer (matikan penyisipan) vs dengan pacer; jalur `Native` vs `Soft`.
    Tentukan penyebab dari data, bukan dari dugaan.
C5. Perbaiki penyebab yang terbukti. Tambahkan tes di `recorder/` untuk logika yang bisa diuji tanpa perangkat keras (mis. Pacer dengan jitter),
    jalankan `cargo test` dan `cargo clippy` di folder `recorder`. Rekam ulang 2 menit lalu ulangi C2: patah-patah harus hilang menurut angka.

## Bagian D. Verifikasi akhir
D1. Rekam 10 menit rapat nyata (atau campuran ucapan jelas dan senyap yang disengaja). Proses. Transkrip tidak boleh kosong; jumlah segmen
    wajar; GPU dipakai (`loading whisper large-v3 on cuda` di `backend.log`); catat VRAM puncak.
D2. Pemisah pembicara berjalan atau gagal dengan catatan yang jelas (bukan hilangnya transkrip).
D3. `pytest server` dan (bila menyentuh perekam) `cargo test` di `recorder` lulus. Jalankan juga `ruff check` bila repo memakainya.

## Laporan
Tulis `docs/v2/LOCAL_DEBUG_NVIDIA_RESULTS.md`: tiap butir LULUS / GAGAL / TIDAK BISA DIUJI dengan bukti (angka, keluaran, baris log), akar masalah
yang terbukti vs yang masih dugaan, daftar commit, dan apa yang BELUM terselesaikan. Jangan menyatakan "beres" tanpa angka sebelum/sesudah.
````

---

## Prompt 2. PC Intel (Core Ultra 7 155H, iGPU)

````text
Kamu bekerja di PC Windows dengan Intel Core Ultra 7 155H (iGPU Arc) pada aplikasi "Rekamind" (repo ini, branch `feat/amd-vulkan`).
Balas dalam Bahasa Indonesia. Tugasmu: JALANKAN aplikasinya, REPRODUKSI masalah di bawah, cari akar masalahnya dengan bukti,
PERBAIKI kodenya di sesi ini, lalu uji ulang.

## Aturan
- Jujur dan berbukti. Pisahkan "terbukti (ada keluaran/ukuran)" dari "dugaan". Beri label [High/Medium/Low confidence] pada klaim penting.
- Jangan menulis rahasia (kunci API, token HF, token login) di laporan atau commit. Jangan mengarang nilai; kalau tidak bisa diukur, tulis TIDAK DIUKUR.
- Jangan skip/matikan tes untuk membuat hijau. Jangan merge ke master, jangan buat PR. Kerjakan di branch `feat/amd-vulkan`
  (atau cabang baru darinya), commit kecil dengan pesan jelas, push hanya setelah tes lulus.
- Sebelum mengubah kode, tulis dulu hipotesis dan cara membuktikannya. Jalur CPU dan NVIDIA tidak boleh rusak: `pytest server` sebelum push
  (lihat `server/tests/test_engine_regression.py`).
- Baca `docs/v2/INTEL_GPU_TEST.md` untuk skenario uji Intel yang sudah ada dan jangan mengulang yang sudah lulus tanpa alasan.

## Masalah
1. Pemasangan mesin Intel (OpenVINO) berhasil, tetapi saat mengonversi `openai/whisper-large-v3` muncul peringatan
   `You are using a model of type whisper to instantiate a model of type fun_asr`. Belum diketahui fatal atau tidak.
2. Rekaman 10 menit menghasilkan "Tidak ada ucapan terdeteksi dalam rekaman ini..." (transkrip kosong). Tidak ada hasil sama sekali.
3. `speaker.wav` hasil rekaman terdengar patah-patah. Belum diketahui apakah `mic.wav` juga. Mesin NVIDIA (PC lain) juga memberi hasil kosong,
   jadi audio/perekam adalah tersangka bersama; mesin Intel bisa punya masalah tambahan sendiri. Pisahkan keduanya.

## Konteks kode
- Mesin Intel: `server/rekamind_server/engines/openvino.py` (`prepare_model` mengonversi model lewat `OVModelForSpeechSeq2Seq.from_pretrained(...,
  export=True)`; jendela 30 dtk; jendela dengan RMS < 0,003 DILEWATI sebagai senyap; timestamp lewat `return_timestamps=True` dengan cadangan satu segmen
  per jendela; cadangan GPU -> CPU; IR di-cache di `%USERPROFILE%\.rekamind\openvino-models` atau `REKAMIND_DATA_DIR`).
  Pemasangan paket: `server/rekamind_server/enginepack.py` (`PACKAGES["openvino"]`, `_check_openvino`, `warmup`).
- Tumpukan terbaru (optimum-intel, transformers, openvino) berbeda dari yang divalidasi di v1 pada mesin yang sama. Periksa versi terpasang di
  `backend\engine-pack` dan bandingkan dengan yang ada di `PACKAGES["openvino"]`.
- Perekam: `recorder/src/backend/wasapi_backend.rs`, `recorder/src/timeline.rs` (`Pacer`, `MIN_GAP_MS = 120`), `sink.rs`, `session.rs`, `resample.rs`.
  `--stats` hanya mengukur CPU/memori, bukan putusnya audio.
- Pipeline: `server/rekamind_server/pipeline.py` (`_transcribe_and_store`; ASR kosong -> catatan "Tidak ada ucapan terdeteksi").
- Data aplikasi: `%LOCALAPPDATA%\id.rekamind.desktop\` (`recordings\`, `backend\recordings\<id>\mic.wav|speaker.wav`, `backend\logs\backend.log`,
  `backend\engine-pack\`). Folder `AppData` tersembunyi.
- Bangun/jalankan lokal: README bagian "For developers". Catat apakah memakai installer atau menjalankan dari kode.

## Langkah 0. Siapkan
- Catat: nama dan versi driver iGPU (`Get-CimInstance Win32_VideoController`), RAM, versi Windows, perangkat keluaran/masukan audio default.
- `git log --oneline -5`. Jika memakai installer, baris pertama log pemasangan = `Rekamind <versi>, build <sha>`, `<sha>` bukan `8fe8a93`.

## Bagian A. Mesin Intel berdiri sendiri (tanpa perekam)
A1. Jalankan `rekamind-backend.exe engines status` dan `engines check` (atau padanannya dari kode). Catat `kind`, daftar GPU, hasil cek OpenVINO.
A2. Telusuri peringatan `fun_asr`: catat versi `transformers`, `optimum`, `optimum-intel`, `openvino`, `nncf` yang terpasang. Tentukan apakah konversi
    SELESAI (ada `openvino_encoder_model.xml` di folder IR) dan modelnya benar-benar Whisper. Jika konversi tidak selesai atau modelnya salah dimuat,
    cari akar penyebab (ketidakcocokan versi? `AutoConfig`/`model_type`?) dan perbaiki (pin versi di `PACKAGES["openvino"]` dan/atau penyesuaian
    `engines/openvino.py`). Pasang ulang bersih bila perlu dan ulangi.
A3. Buat/ambil satu WAV ucapan Indonesia yang JELAS, mono 16 kHz, 1-2 menit, simpan di luar repo. Jalankan transkripsi lewat mesin Intel
    (unggah sebagai rapat, atau `python -m rekamind_server.bench <wav> --model large-v3 --device intel`; cek `--help`, opsi bisa berbeda).
    Catat: perangkat aktual (GPU atau jatuh ke CPU?), waktu, RTF, jumlah segmen, apakah timestamp per segmen benar atau hanya satu segmen per jendela,
    dan kualitas teksnya (bandingkan dengan teks yang kamu tahu). Ini membuktikan mesin Intel sehat TANPA perekam.
A4. Ulangi A3 dengan `--device cpu` pada WAV yang sama sebagai pembanding. Jika CPU berhasil dan Intel kosong/salah: bug ada di `engines/openvino.py`.
    Periksa terutama ambang senyap `SILENCE_RMS` (apakah WAV normal terbuang?), `return_timestamps`, dan dekode token.

## Bagian B. Rekaman patah-patah (bagian perekam sama dengan PC NVIDIA)
B1. Rekam 2 menit sambil memutar ucapan jelas dari speaker dan berbicara ke mikrofon (jangan 10 menit dulu).
B2. Analisis `mic.wav` dan `speaker.wav` dengan skrip Python (`python -I`, skrip di luar repo): durasi vs durasi sebenarnya, jumlah run nol persis
    > 20 ms, total detik nol, RMS per detik, persentase detik senyap. Tulis angkanya, bukan hanya kesan pendengaran.
B3. Tambahkan penghitung diagnostik di perekam (jumlah penyisipan senyap `Pacer`, total sampel disisipkan, selisih jam perangkat vs jam dinding,
    jalur `Convert::Native` atau `Convert::Soft`, flag paket WASAPI yang bisa dibaca). Catat ke log. Ulangi B1-B2.
B4. Bandingkan satu variabel per percobaan: speaker bawaan vs headset USB/Bluetooth/HDMI; aplikasi audio lain; `POLL` 100 ms vs 10 ms; dengan vs tanpa
    pacer; jalur `Native` vs `Soft`. Tentukan penyebab dari data.
B5. Perbaiki penyebab yang terbukti, tambahkan tes di `recorder/` untuk logika yang bisa diuji tanpa perangkat keras, jalankan `cargo test` dan
    `cargo clippy` di folder `recorder`. Rekam ulang 2 menit dan ulangi B2: patah-patah hilang menurut angka.

## Bagian C. Verifikasi akhir
C1. Rekam 10 menit rapat nyata, proses dengan mesin Intel. Transkrip tidak boleh kosong; catat GPU yang dipakai, waktu, memori puncak.
C2. Pemisah pembicara (bila dicentang) berjalan atau gagal dengan catatan jelas, tanpa menghilangkan transkrip.
C3. `pytest server`, `cargo test` (bila menyentuh perekam), `ruff check` lulus.

## Laporan
Tulis `docs/v2/LOCAL_DEBUG_INTEL_RESULTS.md`: tiap butir LULUS / GAGAL / TIDAK BISA DIUJI dengan bukti (angka, keluaran, baris log), akar masalah
yang terbukti vs dugaan, versi paket yang terpasang, daftar commit, dan apa yang BELUM terselesaikan. Jangan menyatakan "beres" tanpa angka
sebelum/sesudah.
````
