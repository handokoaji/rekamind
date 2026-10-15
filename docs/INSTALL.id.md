🌐 [English](INSTALL.md) · **Bahasa Indonesia**

# Memasang Rekamind

## Aplikasi desktop (Windows, Linux)

1. Pasang installer (`Rekamind_x.y.z_x64-setup.exe` di Windows, `.deb` di Linux). Installer **sudah membawa mesin
   lokalnya** (API, antrean, SQLite); tidak perlu Python.
2. Buka Rekamind. Anda langsung bisa merekam (tombol atau `Ctrl+Alt+R`). Saat merekam, hanya perekam kecil yang
   berjalan; jendela boleh ditutup.
3. Untuk transkrip, ringkasan, dan task: **Pengaturan → Mesin transkripsi → Pasang** (pilih CPU atau NVIDIA GPU).
   Ini mengunduh beberapa GB sekali saja, dengan progres dan tombol batal. Lalu **Uji mesin**.
4. Isi **Layanan ringkasan** (mis. kunci API Groq). Kunci disimpan di penyimpanan kredensial sistem.
5. Model suara diunduh saat rapat pertama diproses, atau klik **Unduh model sekarang**.

> **Dukungan GPU:** hanya CPU dan NVIDIA CUDA yang ditawarkan. **GPU AMD (dan Intel) belum didukung dan belum pernah diuji**; mesin tersebut berjalan di CPU.

Pemisah pembicara (pyannote) opsional: centang saat memasang, isi token Hugging Face, dan setujui syarat model
`pyannote/speaker-diarization-3.1` di akun Hugging Face Anda.

Data aplikasi (Windows: `%LOCALAPPDATA%\\id.rekamind.desktop`): `recordings\\` (rekaman), `backend\\` (SQLite, model,
`engine-pack\\`, `logs\\backend.log`). Menghapus folder `engine-pack` mengembalikan ke keadaan sebelum dipasang.

## Server bersama (kantor)

### Tercepat: image siap-pakai (Portainer atau Docker biasa, tanpa build)

Image dipublikasikan di GitHub Container Registry pada setiap rilis:

| Image | Fungsi |
|---|---|
| `ghcr.io/handokoaji/rekamind-server:<versi>-cpu` | Backend lengkap, **transkripsi di CPU**. Disarankan. Mengunduh model Whisper saat pertama dipakai ke volume data. |
| `ghcr.io/handokoaji/rekamind-server:<versi>-cuda` | Sama, **transkripsi di GPU NVIDIA** (CUDA 12; host perlu driver NVIDIA + NVIDIA Container Toolkit). Pakai [`docker-compose.image-gpu.yml`](../docker-compose.image-gpu.yml). Ditujukan untuk kartu seperti RTX 4060 (8 GB); belum diverifikasi di perangkat keras sungguhan. |
| `ghcr.io/handokoaji/rekamind-server:<versi>` | Hanya API: rekam/unggah/lihat/ekspor. **Tidak memproses rapat.** |

`<versi>` contohnya `0.4.0-beta.1`; `beta` / `beta-cpu` / `beta-cuda` selalu menunjuk beta terbaru. Image `-cpu` memakai model Whisper `small` (bawaan; terima proses lebih lambat bila memakai yang lebih besar); `-cuda` memakai `large-v3`. GPU AMD/Intel belum didukung (pakai `-cpu`). Pemisah pembicara (pyannote) tidak termasuk dalam image.

1. Buat OAuth client Google ([AUTH.id.md](AUTH.id.md)).
2. **Portainer:** *Stacks → Add stack → Web editor*, tempel [`docker-compose.image.yml`](../docker-compose.image.yml), isi variabel lingkungan (`REKAMIND_PUBLIC_URL`, `REKAMIND_GOOGLE_CLIENT_ID`, `REKAMIND_GOOGLE_CLIENT_SECRET`, `REKAMIND_SUPERADMINS`, dan `REKAMIND_LLM_API_KEY` untuk ringkasan), lalu **Deploy**.
   **Docker biasa:** `docker compose -f docker-compose.image.yml up -d` dengan variabel itu di berkas `.env`.
3. Pasang reverse proxy HTTPS di depannya (lihat di bawah) dan arahkan aplikasi desktop ke alamat itu (**Server terpisah**).

> **Bila pull ditolak:** saat pertama kali dipublikasikan, paket GHCR bisa berstatus *private*. Pemilik repositori perlu mengubahnya menjadi **Public** sekali (GitHub → profil → Packages → `rekamind-server` → Package settings → Change visibility). Image baru dibangun dan dijalankan di CI/sandbox; transkripsi di dalam container belum diverifikasi dengan rapat sungguhan (beta).

### Bangun sendiri

`docker compose up -d --build`, atau tempel `docker-compose.yml` sebagai stack di Portainer. Wajib mengisi login Google
milik Anda sendiri: lihat [AUTH.id.md](AUTH.id.md). Aplikasi desktop lalu dipilih ke mode **Server terpisah**.

### Di belakang reverse proxy (nginx, Caddy, Traefik)

Rapat panjang berarti unggahan besar: 2 jam = ±460 MB (dua WAV). File non-WAV (mp3/m4a) diubah ke WAV oleh server
saat diunggah; 2 jam m4a stereo butuh ±55 detik. Atur proxy agar tidak memutus ini, mis. nginx:

```nginx
client_max_body_size 4g;          # sama dengan REKAMIND_MAX_UPLOAD_MB (bawaan 4096)
proxy_request_buffering off;      # alirkan ke server, jangan tampung dulu di disk proxy
proxy_read_timeout 600s;
proxy_send_timeout 600s;
```

## Membangun installer sendiri

```bash
pip install -e "server[dev]" pyinstaller
python scripts/build_desktop.py            # Windows: nsis, Linux: deb
python scripts/smoke_backend.py desktop/src-tauri/resources/backend/rekamind-backend
```
