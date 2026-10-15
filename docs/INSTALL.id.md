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
