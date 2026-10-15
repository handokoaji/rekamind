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

### Fastest: prebuilt image (Portainer or plain Docker, nothing to build)

Images are published on GitHub Container Registry with every release:

| Image | What it does |
|---|---|
| `ghcr.io/handokoaji/rekamind-server:<version>-cpu` | Full backend, **transcribes on the CPU**. Recommended. Downloads the Whisper model on first use into the data volume. |
| `ghcr.io/handokoaji/rekamind-server:<version>-cuda` | Same, **transcribes on an NVIDIA GPU** (CUDA 12; host needs the NVIDIA driver + NVIDIA Container Toolkit). Use [`docker-compose.image-gpu.yml`](../docker-compose.image-gpu.yml). Intended for cards such as an RTX 4060 (8 GB); not yet verified on real hardware. |
| `ghcr.io/handokoaji/rekamind-server:<version>` | API only: record/upload/view/export. **Does not process meetings.** |

`<version>` is e.g. `0.4.0-beta.1`; `beta` / `beta-cpu` / `beta-cuda` always point to the newest beta. The `-cpu` image defaults to the `small` Whisper model (accept slower processing to use a larger one); `-cuda` defaults to `large-v3`. AMD/Intel GPUs are not supported (use `-cpu`). Speaker separation (pyannote) is not included in the images.

1. Create a Google OAuth client ([AUTH.md](AUTH.md)).
2. **Portainer:** *Stacks → Add stack → Web editor*, paste [`docker-compose.image.yml`](../docker-compose.image.yml), fill the environment variables (`REKAMIND_PUBLIC_URL`, `REKAMIND_GOOGLE_CLIENT_ID`, `REKAMIND_GOOGLE_CLIENT_SECRET`, `REKAMIND_SUPERADMINS`, and `REKAMIND_LLM_API_KEY` for summaries), **Deploy**.
   **Plain Docker:** `docker compose -f docker-compose.image.yml up -d` with those variables in a `.env` file.
3. Put an HTTPS reverse proxy in front (see below) and point the desktop app to it (**Server terpisah** / Remote server).

> **If the pull is denied:** the first time a package is published to GHCR it can be *private*. The repository owner must set the package to **Public** once (GitHub → profile → Packages → `rekamind-server` → Package settings → Change visibility). The image has only been built and started in CI/sandbox so far; transcription inside the container has not been verified against a real meeting (beta).

### Build it yourself

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
