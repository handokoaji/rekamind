🌐 **English** · [Bahasa Indonesia](INSTALL.id.md)

# Installing Rekamind

## Desktop app (Windows, Linux)

1. Install the installer (`Rekamind_x.y.z_x64-setup.exe` on Windows, `.deb` on Linux). The installer **already
   bundles its local engine** (API, queue, SQLite); Python is not needed.
2. Open Rekamind. You can start recording right away (button or `Ctrl+Alt+R`). While recording, only a small
   recorder runs; the window may be closed.
3. For transcripts, summaries, and tasks: **Pengaturan** (Settings) → **Mesin transkripsi** (Transcription engine) → **Pasang** (Install) (choose CPU or NVIDIA GPU).
   This downloads several GB, once only, with progress and a cancel button. Then **Uji mesin** (Test engine).
4. Fill in **Layanan ringkasan** (Summary service) (e.g. a Groq API key). The key is stored in the system credential store.
5. The speech models are downloaded when the first meeting is processed, or click **Unduh model sekarang** (Download models now).

> **GPU support:** only CPU and NVIDIA CUDA are offered. **AMD (and Intel) GPUs are not supported and have never been tested**; those machines run on the CPU.

Speaker separation (pyannote) is optional: tick it during installation, enter a Hugging Face token, and accept the terms of the
`pyannote/speaker-diarization-3.1` model on your Hugging Face account.

App data (Windows: `%LOCALAPPDATA%\\id.rekamind.desktop`): `recordings\\` (recordings), `backend\\` (SQLite, models,
`engine-pack\\`, `logs\\backend.log`). Deleting the `engine-pack` folder returns things to the state before installation.

## Shared server (office)

`docker compose up -d --build`, or paste `docker-compose.yml` as a stack in Portainer. You must fill in your own Google
login: see [AUTH.md](AUTH.md). The desktop app is then switched to **Server terpisah** (Separate server) mode.

### Behind a reverse proxy (nginx, Caddy, Traefik)

Long meetings mean large uploads: 2 hours = ±460 MB (two WAVs). Non-WAV files (mp3/m4a) are converted to WAV by the server
on upload; 2 hours of stereo m4a takes ±55 seconds. Configure the proxy so it does not cut these off, e.g. nginx:

```nginx
client_max_body_size 4g;          # same as REKAMIND_MAX_UPLOAD_MB (default 4096)
proxy_request_buffering off;      # stream to the server, don't buffer to the proxy's disk first
proxy_read_timeout 600s;
proxy_send_timeout 600s;
```

## Building your own installer

```bash
pip install -e "server[dev]" pyinstaller
python scripts/build_desktop.py            # Windows: nsis, Linux: deb
python scripts/smoke_backend.py desktop/src-tauri/resources/backend/rekamind-backend
```
