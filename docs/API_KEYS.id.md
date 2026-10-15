🌐 [English](API_KEYS.md) · **Bahasa Indonesia**

# Cara mendapatkan token Hugging Face dan kunci API Groq

Rekamind bekerja di komputer Anda sendiri, tetapi dua fitur opsional membutuhkan akun di layanan luar:

| Anda ingin | Yang dibutuhkan | Diisi di |
|---|---|---|
| **Pemisah pembicara** (siapa bicara apa) | **Token Hugging Face** | Pengaturan → *Token Hugging Face* |
| **Ringkasan dan task** yang ditulis AI | **Kunci API Groq** (atau layanan lain yang kompatibel OpenAI) | Pengaturan → *Kunci API ringkasan* |

Merekam dan transkripsi tetap berjalan **tanpa** keduanya. Keduanya gratis dibuat; isinya hanyalah kredensial Anda sendiri, dan
Rekamind menyimpannya di penyimpanan kredensial sistem operasi (Windows Credential Manager), bukan di berkas pengaturan.

> Catatan: yang dimaksud adalah **Groq** (dengan **Q**, layanan inferensi AI), bukan "Grok" milik xAI.

Nama tombol di situs web bisa berubah dari waktu ke waktu. Bila namanya sedikit berbeda, pilih yang paling mirip.

---

## 1. Token Hugging Face (pemisah pembicara)

Pemisah pembicara memakai model `pyannote`. Model ini *gated*: Hugging Face hanya mengizinkan akun yang sudah menyetujui
syaratnya untuk mengunduh, dan token Anda adalah bukti bagi Rekamind bahwa itu memang Anda. Ada **dua langkah**: setujui syarat model,
lalu buat token.

### 1a. Buat akun
1. Buka <https://huggingface.co/join> dan daftar (email, atau masuk dengan Google/GitHub).
2. Konfirmasi alamat email dari pesan yang dikirim Hugging Face.

### 1b. Setujui syarat model (lakukan sebelum membuat token)
Buka tiap halaman di bawah ini dalam keadaan masuk, baca formulir singkatnya, lalu tekan tombol persetujuan
(biasanya **Agree and access repository**). Isi kolom perusahaan/universitas dan tujuan penggunaan bila diminta.

1. <https://huggingface.co/pyannote/speaker-diarization-3.1>
2. <https://huggingface.co/pyannote/segmentation-3.0>

Bila berhasil, halaman menampilkan berkas model, bukan lagi formulir ("You have been granted access to this model").

### 1c. Buat token
1. Buka <https://huggingface.co/settings/tokens>.
2. Klik **Create new token** (atau **+ Create new token**).
3. Pilih tipe **Read**. Jika memakai token *Fine-grained*, aktifkan
   *Read access to contents of all public gated repos you can access*.
4. Beri nama, misalnya `rekamind`, lalu klik **Create token**.
5. **Salin token sekarang** (diawali `hf_`). Hugging Face hanya menampilkannya sekali; bila hilang, buat token baru.

### 1d. Berikan ke Rekamind
1. Buka Rekamind → **Pengaturan**.
2. Pastikan **Tempat pemrosesan** adalah *Komputer ini (GPU lokal)*.
3. Tempel token ke kolom **Token Hugging Face**, lalu klik **Simpan** di bagian bawah halaman.
4. Di panel **Mesin transkripsi**, biarkan **Sertakan pemisah pembicara** tercentang, lalu klik tombol pasang sesuai perangkat keras Anda.
   Tombol pasang tetap nonaktif sampai token tersimpan; hilangkan centang bila Anda tidak butuh pemisah pembicara.
5. Setelah terpasang, ubah **Pemisah pembicara** menjadi **pyannote (perlu paket + token)** dan klik **Simpan** lagi.
6. Buka rapat lalu klik **Proses ulang**. Transkrip sekarang menampilkan pembicara yang terpisah.

---

## 2. Kunci API Groq (ringkasan dan task)

Ringkasan, keputusan, dan daftar task ditulis oleh model bahasa. Rekamind bisa memakai **layanan apa pun yang kompatibel OpenAI**;
**Groq** hanyalah bawaan, bukan keharusan. Bila Anda sudah memakai penyedia lain, langsung ke
[Memakai layanan lain yang kompatibel OpenAI](#memakai-layanan-lain-yang-kompatibel-openai).

### 2a. Buat akun
1. Buka <https://console.groq.com> lalu klik **Sign up** (Google, GitHub, atau email).
2. Selesaikan pendaftaran. Groq menyediakan paket gratis dengan batas pemakaian; lihat konsol untuk batas dan harga terbaru.

### 2b. Buat kunci
1. Di konsol, buka **API Keys** (menu kiri, atau <https://console.groq.com/keys>).
2. Klik **Create API Key**, beri nama misalnya `rekamind`, lalu konfirmasi.
3. **Salin kunci sekarang** (diawali `gsk_`). Kunci hanya ditampilkan sekali; bila hilang, buat kunci baru.

### 2c. Berikan ke Rekamind
1. Buka Rekamind → **Pengaturan** → **Pemrosesan di komputer ini**.
2. Periksa nilai bawaan yang sudah mengarah ke Groq:
   - **Layanan ringkasan (OpenAI-compatible)**: `https://api.groq.com/openai/v1`
   - **Model ringkasan**: `openai/gpt-oss-120b` (ganti dengan model lain dari konsol Groq bila yang ini sudah dihentikan)
3. Tempel kunci ke **Kunci API ringkasan**, lalu klik **Simpan**.
4. Proses sebuah rapat (**Proses sekarang**). Tab **Ringkasan** dan **Task** terisi setelah selesai.

> **Privasi:** untuk menulis ringkasan, *teks transkrip* dikirim ke layanan yang Anda pilih. Audionya tidak dikirim.
> Bila itu tidak boleh untuk rapat Anda, pakai server lokal yang kompatibel OpenAI seperti Ollama dan isi alamatnya di
> **Layanan ringkasan**, atau lewati ringkasan.

---

## Memakai layanan lain yang kompatibel OpenAI

Layanan apa pun yang memakai API chat OpenAI bisa dipakai. Anda hanya mengubah tiga kolom di
**Pengaturan → Pemrosesan di komputer ini** (kolom layanan ringkasan, di layar yang sama dengan langkah 2c):

| Kolom | Isi dengan |
|---|---|
| **Layanan ringkasan (OpenAI-compatible)** | *Base URL* layanan (biasanya berakhiran `/v1`) |
| **Model ringkasan** | Nama model persis seperti yang diberikan layanan |
| **Kunci API ringkasan** | Kunci dari layanan itu (kosongkan bila tidak memerlukan) |

Contoh umum (cek dokumentasi masing-masing penyedia untuk nilai terbaru):

| Layanan | Base URL | Kunci |
|---|---|---|
| Groq (bawaan) | `https://api.groq.com/openai/v1` | `gsk_…` dari console.groq.com |
| OpenAI | `https://api.openai.com/v1` | `sk-…` dari platform.openai.com |
| Ollama di komputer ini | `http://localhost:11434/v1` | tidak perlu |
| Server lain (vLLM, LM Studio, OpenRouter, gateway kantor…) | URL sesuai dokumentasinya | sesuai dokumentasinya |

Pilih model yang patuh instruksi dan bisa menulis bahasa Indonesia; model lokal yang sangat kecil sering menghasilkan ringkasan
yang buruk. Model harus mengembalikan jawaban terstruktur (JSON); bila ringkasan gagal pada model pilihan Anda, coba yang lebih besar.

---

## Pemecahan masalah

| Gejala | Kemungkinan penyebab dan solusi |
|---|---|
| Tombol pasang abu-abu dengan "Token Hugging Face wajib diisi" | Token belum tersimpan. Tempel di **Token Hugging Face** lalu klik **Simpan**, atau hilangkan centang pemisah pembicara. |
| "Pemisah pembicara gagal …" pada rapat | Token salah atau kedaluwarsa, atau syarat **kedua** model di langkah 1b belum disetujui. Setujui, lalu **Proses ulang**. |
| Hasil tetap satu pembicara | **Pemisah pembicara** masih *Tanpa*. Ubah ke *pyannote* lalu simpan. |
| `401` / "invalid token" dari layanan ringkasan | Kunci Groq salah ketik atau sudah dicabut. Buat kunci baru dan tempel ulang. |
| `429` / "rate limit" | Batas layanan tercapai. Tunggu semenit lalu proses ulang, atau pakai paket atau model lain. |
| "Ringkasan gagal" dengan nama model | Model sudah diganti nama atau dihentikan. Pilih yang terbaru di konsol Groq dan isi di **Model ringkasan**. |

## Menjaga kunci tetap aman
- Perlakukan keduanya seperti kata sandi: jangan dibagikan di chat, tangkapan layar, issue, atau commit.
- Bila bocor, **cabut** di situsnya (Hugging Face → Access Tokens, Groq → API Keys) dan buat yang baru.
- Rekamind tidak pernah menulisnya ke `settings.json`; untuk menghapus, ganti di **Pengaturan** atau hapus entrinya di
  Windows Credential Manager.
