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

> **GPU support:** CPU and NVIDIA CUDA are supported. **Intel GPU** (integrated, e.g. Core Ultra 7 155H) is **experimental** through OpenVINO: choose **Pasang untuk Intel GPU** (Install for Intel GPU), then **Uji mesin**; it should list `GPU` among the devices. Works on one Core Ultra 7 155H by the maintainer's manual check; speed and accuracy have not been measured. The first meeting converts the model (minutes, several GB of RAM) and caches it. The glossary is not applied on this engine. **AMD GPU** (integrated Radeon 680M/780M/860M and other Vulkan-capable GPUs) is **experimental** through Vulkan (whisper.cpp): choose **Pasang untuk GPU AMD (Vulkan)** (Install for AMD GPU), then **Unduh model ... sekarang** and **Uji mesin**; it should list your Radeon under "GPU detected". The install downloads a small program from this project's GitHub release `engine-assets` (checked against a SHA-256) and the model from Hugging Face (large-v3 quantised, ~1 GB); the glossary is not applied. Not yet verified on real hardware. Other machines run on the CPU.

Speaker separation (pyannote) is ticked by default during installation and **needs a Hugging Face token**: the install buttons stay
disabled until the token is saved (paste it in the notice), or untick the box to install without it. Accept the terms of the
`pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` models on your Hugging Face account. After an install with
speaker separation succeeds the setting is switched on automatically. If similar voices still get merged, set **Jumlah pembicara**
(number of speakers) in the meeting's Speakers tab and click **Pisahkan ulang** (Separate again). Step-by-step guide for the Hugging Face token and for a
summary-service key (Groq or any OpenAI-compatible service): [API_KEYS.md](API_KEYS.md).

App data (Windows: `%LOCALAPPDATA%\\id.rekamind.desktop`): `recordings\\` (recordings), `backend\\` (SQLite, models,
`engine-pack\\`, `logs\\backend.log`). Deleting the `engine-pack` folder returns things to the state before installation.

## Slow or interrupted engine install

The first engine install downloads a lot: the CPU engine is a few hundred MB, an **NVIDIA** install adds about **1.3 GB** of
CUDA libraries (cuDNN ≈ 740 MB and cuBLAS ≈ 550 MB, from `files.pythonhosted.org`), and speaker separation (pyannote) adds PyTorch
(GBs). On a slow link this takes a long time; the engine panel now shows a line every few seconds (MB, percent, speed) and a warning
when a download makes no progress for a minute.

- **Read the first lines of the install log** (Pengaturan → Mesin transkripsi). They show the pip version, which package sources and
  proxies apply (credentials masked), and how fast `pypi.org` / `files.pythonhosted.org` answer from this computer. Include them in a bug report.
- **Cancel and try again**: downloads resume where they stopped (pip 25.1 or newer, bundled in current builds).
- **A terminal can be faster than the installed app** if your network settings live only in that terminal session. The app does not see
  variables set only in a terminal. Set them as **user environment variables** (Windows: System Properties → Environment Variables):
  `HTTPS_PROXY`, `PIP_INDEX_URL` (a nearer package mirror, if your organisation has one), `PIP_FIND_LINKS` (below). Then restart Rekamind.
- **Offline / very slow link**: on a faster machine run `pip download faster-whisper nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" -d wheels --only-binary=:all: --platform win_amd64 --python-version 3.13`
  (adjust for your system), copy the `wheels` folder, set `PIP_FIND_LINKS` to it and install from the app.

## Shared server (office)

### Fastest: prebuilt image (Portainer or plain Docker, nothing to build)

Images are published on GitHub Container Registry with every release:

| Image | What it does |
|---|---|
| `ghcr.io/handokoaji/rekamind-server:<version>-cpu` | Full backend, **transcribes on the CPU**. Recommended. Downloads the Whisper model on first use into the data volume. |
| `ghcr.io/handokoaji/rekamind-server:<version>-cuda` | Same, **transcribes on an NVIDIA GPU** (CUDA 12; host needs the NVIDIA driver + NVIDIA Container Toolkit). Use [`docker-compose.image-gpu.yml`](../docker-compose.image-gpu.yml). Intended for cards such as an RTX 4060 (8 GB); not yet verified on real hardware. |
| `ghcr.io/handokoaji/rekamind-server:<version>` | API only: record/upload/view/export. **Does not process meetings.** |

`<version>` is e.g. `0.4.0-beta.2`; `beta` / `beta-cpu` / `beta-cuda` / `beta-cuda-diarize` always point to the newest beta. The `-cpu` image defaults to the `small` Whisper model (accept slower processing to use a larger one); `-cuda` defaults to `large-v3`. AMD/Intel GPUs are not supported (use `-cpu`). Speaker separation (pyannote) is only in the **`-cuda-diarize`** image (NVIDIA GPU; several GB larger because it carries PyTorch). To use it: pick that image tag, set `REKAMIND_DIARIZER=pyannote` and `REKAMIND_HF_TOKEN` to a Hugging Face token whose account accepted the terms of the `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` models. Without it every voice on the computer's audio is one speaker. It adds about 1-2 GB of VRAM next to Whisper (an estimate, not yet measured). The first transcription downloads the Whisper model (about 3 GB for `large-v3`) into the data volume.

1. Create a Google OAuth client ([AUTH.md](AUTH.md)).
2. **Portainer:** *Stacks → Add stack → Web editor*, paste [`docker-compose.image.yml`](../docker-compose.image.yml), fill the environment variables (`REKAMIND_PUBLIC_URL`, `REKAMIND_GOOGLE_CLIENT_ID`, `REKAMIND_GOOGLE_CLIENT_SECRET`, `REKAMIND_SUPERADMINS`, and `REKAMIND_LLM_API_KEY` for summaries), **Deploy**.
   **Plain Docker:** `docker compose -f docker-compose.image.yml up -d` with those variables in a `.env` file.
3. Put an HTTPS reverse proxy in front (see below) and point the desktop app to it (**Server terpisah** / Remote server). The compose files already allow the desktop app's origins through `REKAMIND_CORS_ORIGINS`; without it the app says it cannot reach the server although the server is up.

> **If the pull is denied:** the package may be *private*. For `v0.4.0-beta.2` it was verified to be public (anonymous pull works). If it is private for you, the repository owner sets it to **Public** (GitHub → profile → Packages → `rekamind-server` → Package settings → Change visibility). The image has only been built and started in CI/sandbox so far; transcription inside the container has not been verified against a real meeting (beta).

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
