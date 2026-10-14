# Daftar uji di PC (satu-satunya yang tersisa)

Semua yang bisa diuji tanpa perangkat sudah otomatis lulus (lihat `docs/v2/ARCHITECTURE.md`). Yang di bawah ini
memang butuh Windows, GPU, atau akun Google asli. Urutannya dari yang paling murah. Tulis hasil tiap butir
(lulus / gagal + pesan) dan kirim; `backend.log` dan `rekamind-rec ... --stats` biasanya cukup untuk diagnosis.

## A. Windows 10/11 tanpa GPU khusus
1. Pasang `.exe` dari artifact CI (job *desktop*, Windows). **Catat**: apakah SmartScreen/antivirus memperingatkan
   (installer belum ditandatangani; ini diharapkan).
2. Buka aplikasi. Harus muncul jendela dan ikon tray. Tidak boleh ada jendela konsol hitam berkedip.
3. Setel nama Anda, tekan `Ctrl+Alt+R`, putar video YouTube + bicara ke mikrofon 1 menit, tekan lagi.
   Harapan: rekaman ter-unggah, rapat muncul "Siap diproses". Buka Task Manager saat merekam: catat CPU/RAM
   `rekamind.exe` dengan jendela **tertutup** (target: RAM < 100 MB, CPU ≈ 0–1%).
4. Dengarkan hasil WAV di `%LOCALAPPDATA%\\id.rekamind.desktop\\recordings\\...`: kedua kanal terdengar? (tes WASAPI loopback)
5. Pasang/cabut headset saat merekam: harus muncul "menyambung ulang", bukan berhenti.
6. Matikan paksa aplikasi saat merekam (Task Manager → End task), buka lagi: rekaman muncul di "belum terunggah".
7. Pengaturan → Mesin transkripsi → Pasang (CPU) → Uji mesin. Catat durasi, ukuran folder `engine-pack`, dan apakah
   jalur panjang (>260 karakter) menimbulkan galat.
8. Isi kunci API Groq, proses rapat 1 menit dengan model `small`. Harapan: transkrip bahasa Indonesia + task.
9. Tutup aplikasi, buka lagi: kunci API masih tersimpan (Credential Manager)?

## B. PC dengan GPU NVIDIA
10. Pasang untuk **NVIDIA GPU**, Uji mesin: harus "GPU NVIDIA terdeteksi: 1". Jika gagal, kirim pesan galatnya
    (kemungkinan: versi cuDNN/CUDA tidak cocok dengan driver; ini hipotesis, belum terbukti).
11. `large-v3` pada rekaman rapat nyata 30–60 menit: catat waktu proses dan puncak VRAM.
12. Benchmark akurasi: `python -m rekamind_server.bench --help` (tersedia di checkout kode) pada 2–3 rekaman Indonesia
    yang Anda punya transkrip referensinya. Ini menentukan apakah `large-v3` atau `medium` cukup.
13. Pemisah pembicara (pyannote) + token Hugging Face: apakah "Speaker 1/2" masuk akal pada rapat 3+ orang?

## C. Google asli (server kantor)
14. Buat OAuth client (`docs/AUTH.md`), jalankan `docker compose up`, login dari browser, lalu dari aplikasi desktop
    (mode Server terpisah → Masuk dengan Google). Cek: user biasa hanya melihat rapat sendiri; super admin
    bisa mengelola pengguna.

## D. Server
15. MinIO atau SeaweedFS asli sebagai penyimpanan S3 (`REKAMIND_STORAGE=s3`): unggah, putar audio, hapus rapat.
16. Postgres: `REKAMIND_DATABASE_URL=postgresql+asyncpg://...` — migrasi otomatis jalan, dua pengguna bersamaan.
