<div align="center">

🌐 **English** · [Bahasa Indonesia](README.id.md)

<img src="docs/assets/logo.svg" alt="Rekamind logo" width="96" height="96">

# Rekamind

**Record meetings. Get a per-speaker transcript, a summary and a task list. Your data stays yours.**

[![Release](https://img.shields.io/badge/release-v0.4.0--beta.1-f59e0b?style=for-the-badge)](https://github.com/handokoaji/rekamind/releases/tag/v0.4.0-beta.1)
[![Platform](https://img.shields.io/badge/Windows%20%C2%B7%20Linux-4f46e5?style=for-the-badge)](#-download)
[![License](https://img.shields.io/badge/license-MIT-16a34a?style=for-the-badge)](LICENSE)

[**Download**](#-download) · [Getting started](#-guide-from-install-to-first-use) · [Features](#-features) · [Team server](#-shared-server-for-teams) · [Troubleshooting](#-troubleshooting)

<br>

<img src="docs/screenshots/05-ringkasan.png" alt="Meeting summary in Rekamind" width="880">

</div>

> [!WARNING]
> **This is a beta (0.x) release for testing, not a final release.** The core features are covered by automated
> tests and have been tried on one Windows PC, but not on many machines. **Do not make Rekamind the only copy of a
> recording that matters.** See the honest list of [beta limitations](#-beta-limitations).

> [!NOTE]
> **Language:** the interface is available in **Indonesian (default) and English**; switch with the language selector in the
> top bar (it is also on the sign-in screen). Most screenshots below show the Indonesian interface. The meeting output
> (summary, decisions, tasks) is currently generated **in Indonesian only**, whichever interface language you pick.

## Why Rekamind

- **Light while recording.** A tiny recorder (Rust) captures the microphone and system audio. No AI model runs during
  the meeting, and the window can be closed.
- **Local first.** Transcription (Whisper) and speaker separation run on your computer. Only the transcript text goes
  to the summary service you choose, and that step is optional.
- **From recording to work.** The result is more than text: decisions, the flow of the meeting, and **tasks** with
  assignee, deadline and an evidence quote you can replay.
- **One person or a whole team.** Install on your own laptop, or on an office server with Google sign-in.
- **Open.** MIT licensed. No accounts, no telemetry, no bundled credentials.

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### Record from the desktop
One button or `Ctrl+Alt+R`. Records the microphone and the meeting audio (Zoom, Meet, Teams, ...) as two separate
tracks, so local and remote speakers are easy to tell apart.

</td>
<td width="50%" valign="top">

<img src="docs/screenshots/14-desktop-merekam.png" alt="Recorder bar while recording">

</td>
</tr>
<tr>
<td width="50%" valign="top">

<img src="docs/screenshots/03-unggah.png" alt="Upload a recording">

</td>
<td width="50%" valign="top">

### Or upload a recording
Already have a recording? Upload WAV, MP3 or M4A. The title is filled from the file name.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Summary, decisions, flow of the meeting
Built from the full transcript. Long meetings are split automatically when the summary service limits request size.

</td>
<td width="50%" valign="top">

<img src="docs/screenshots/04-daftar-rapat.png" alt="Meeting list with search and filters">

</td>
</tr>
<tr>
<td width="50%" valign="top">

<img src="docs/screenshots/08-task.png" alt="Review and confirm tasks">

</td>
<td width="50%" valign="top">

### Tasks you can verify
Every task carries an assignee, deadline, estimate and an **evidence quote**. You review and confirm first; nothing
is sent anywhere before you decide.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Per-speaker transcript
Microphone and system audio are separated, speakers are recognised and can be named. Long transcripts stay smooth
(virtualised list).

</td>
<td width="50%" valign="top">

<img src="docs/screenshots/06-transkrip.png" alt="Per-speaker transcript">

</td>
</tr>
<tr>
<td width="50%" valign="top">

<img src="docs/screenshots/09-ekspor.png" alt="Export dialog">

</td>
<td width="50%" valign="top">

### Complete export
One file with summary, decisions, tasks and (optionally) the transcript: **Word (.docx)**, **Markdown** or **JSON**.
Times use your chosen time zone (default WIB, Asia/Jakarta).

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Send tasks to where you work
**GitHub Issues**, **GitLab Issues**, or a signed (HMAC) **webhook** for any task manager. Sending twice does not
create duplicates.

</td>
<td width="50%" valign="top">

<img src="docs/screenshots/10-kirim-task.png" alt="Send tasks to a webhook">

</td>
</tr>
</table>

<details>
<summary><b>More views</b> (speakers, all tasks, settings, dark mode, sign-in)</summary>
<br>

| | |
|---|---|
| ![Speakers](docs/screenshots/07-pembicara.png) <br> **Name the speakers** | ![All tasks](docs/screenshots/11-semua-task.png) <br> **All tasks across meetings** |
| ![Settings](docs/screenshots/12-pengaturan.png) <br> **Settings: integrations and time zone** | ![Engine](docs/screenshots/15-desktop-mesin.png) <br> **Desktop settings: install the local engine** |
| ![Dark](docs/screenshots/05b-ringkasan-gelap.png) <br> **Automatic dark mode** | ![Login](docs/screenshots/01-login.png) <br> **Google sign-in (server mode)** |
| ![English UI](docs/screenshots/16-english-ui.png) <br> **English interface** (language selector, top right) | |

</details>

> Screenshots are taken from the real app with sample meeting content (a "demo" engine), not real model output. The
> quality of your transcripts and summaries depends on the audio, the models and the summary service you use.

## 📥 Download

Pick the file for your system:

| System | File | Notes |
|---|---|---|
| **Windows 10/11 (64-bit)** | [`Rekamind-Windows-x64-setup.exe`](https://github.com/handokoaji/rekamind/releases/download/v0.4.0-beta.1/Rekamind-Windows-x64-setup.exe) | `.exe` installer. No admin rights needed. |
| **Linux (64-bit)** | [`Rekamind-Linux-x64.deb`](https://github.com/handokoaji/rekamind/releases/download/v0.4.0-beta.1/Rekamind-Linux-x64.deb) | Debian/Ubuntu and derivatives. |
| Linux, other distros | [`Rekamind-Linux-x64.AppImage`](https://github.com/handokoaji/rekamind/releases/download/v0.4.0-beta.1/Rekamind-Linux-x64.AppImage) | **Not available in beta.1** (the AppImage build failed; fix planned). Use the `.deb`. |

Every file comes with `SHA256SUMS.txt`. All releases: [Releases](https://github.com/handokoaji/rekamind/releases).

**The installers are not code-signed** (beta). Windows SmartScreen will show "Windows protected your PC": click
**More info → Run anyway**. This is normal for apps without a paid certificate; compare the checksum if in doubt.

**Not supported yet:** macOS and ARM machines. **Intel and AMD GPU acceleration is experimental** (see [GPU support](#gpu-support))
[GPU support](#gpu-support)).

## 🚀 Guide: from install to first use

About 15 minutes, most of it a one-time download.

### Step 1: Install the app

<details open>
<summary><b>Windows</b></summary>

1. Download `Rekamind-Windows-x64-setup.exe` and run it.
2. If SmartScreen appears: **More info → Run anyway**.
3. Follow the installer (Indonesian and English are offered). Rekamind installs for your user only, without admin rights.
4. Open **Rekamind** from the Start menu.

Requirements: 64-bit Windows 10/11. WebView2 ships with Windows 11 and is installed automatically if missing.

</details>

<details>
<summary><b>Linux (Debian / Ubuntu)</b></summary>

```bash
sudo apt install ./Rekamind-Linux-x64.deb      # also pulls in pulseaudio-utils and WebKitGTK
rekamind                                        # or open it from the application menu
```

Recording uses PulseAudio or PipeWire (through `parec`). On PipeWire systems make sure `pipewire-pulse` is installed
(default on Ubuntu 22.10+ and Fedora). For the AppImage: `chmod +x Rekamind-Linux-x64.AppImage`, then run it.

</details>

### Step 2: Try a recording

1. On the **Rapat** (Meetings) page, type a title and click **Mulai merekam** (Start recording), or press `Ctrl+Alt+R` from any app.
2. Hold your meeting as usual. The Rekamind window can be closed; the recorder keeps running in the system tray.
3. When done, press **Stop** (there is a confirmation so you do not stop by accident). The recording is handed to the
   local engine. If **Proses otomatis** (Auto-process) is on in Settings (default), processing starts automatically
   once the engine is installed.

You can already record at this point, even before the AI engine is installed. Recordings wait safely.

### Step 3: Install the transcription engine (once)

Open **Pengaturan → Mesin transkripsi → Pasang** (Settings → Transcription engine → Install).

| Choice | For | Download size |
|---|---|---|
| **CPU** | Every computer, including AMD GPU machines. Slower. | smaller |
| **NVIDIA GPU** | NVIDIA cards with enough VRAM (in our test `large-v3` used 3.3 to 4.2 GB). Much faster. | larger (CUDA libraries) |

There is a progress bar and a cancel button. When it finishes click **Uji mesin** (Test engine); it should say
"Terpasang" (Installed). The speech model downloads when the first meeting is processed (several GB), or click
**Unduh model ... sekarang** (Download model now) to avoid waiting later. The exact download size depends on the
library versions at install time; check your disk space and connection.

> Speaker separation (pyannote) is optional and needs a Hugging Face token. Without it every track is treated as one
> speaker (microphone = you). See [INSTALL.md](docs/INSTALL.md).

#### GPU support

| Hardware | Status |
|---|---|
| **CPU** (any) | Supported. Tested. |
| **NVIDIA GPU** (CUDA) | Supported. Tested on one PC (Windows 11, GTX 1080 Ti). |
| **AMD GPU** (integrated Radeon 680M/780M/860M, e.g. Ryzen 7 7735HS, 8845HS, Ryzen AI 7 350, and other Vulkan-capable GPUs) | **Experimental, via Vulkan (whisper.cpp)** (*Install for AMD GPU (Vulkan)*; not in beta.1). A small native program is downloaded on demand; models are the quantised ggml files (~1 GB for large-v3). **Not yet verified on real hardware**; the first target is the Ryzen AI 7 350 (Radeon 860M). ROCm and DirectML are not used. |
| **Intel GPU** (integrated Arc/Iris Xe, e.g. Core Ultra 7 155H) | **Experimental, via OpenVINO** (*Install for Intel GPU*; not in beta.1). Built on the path validated in v1 on a Core Ultra 7 155H, but **not yet verified in v2 on real hardware**. Large models need several GB of RAM during the one-time conversion; the first meeting is slower because of it. |
| **Intel NPU** | Not supported (evaluated in v1: unreliable on real speech). |

### Step 4: Set up the summary service

Summaries and tasks are produced by a language model through an OpenAI-compatible API. Default: **Groq** (it has a
free tier with usage limits). Under **Pengaturan → Layanan ringkasan** (Settings → Summary service) fill in:

- **API key**: created in your provider account. Stored in Windows Credential Manager or Linux Secret Service, **not**
  in a settings file.
- The address and model are pre-filled for Groq; change them to use another provider (OpenAI, OpenRouter, a local server).

> Privacy: only the **transcript text** is sent to this provider, never audio. If the text must not leave your
> organisation, point it at a model you run yourself, or skip this step (the transcript is still produced).

### Step 5: Process the meeting and review

If **Proses otomatis** is off, open the meeting → **Proses sekarang** (Process now). You will see the status move
(transcription → speakers → summary). Once it reads **Perlu ditinjau** (Needs review):

1. **Ringkasan** (Summary): read the decisions and the flow of the meeting.
2. **Pembicara** (Speakers): name them (Rina, Dewi, ...), then **reprocess** so task assignees link to names.
3. **Task**: check each task (the play button on the evidence quote plays that part of the recording), edit if
   needed, then **Konfirmasi** (Confirm).

### Step 6: Export or send

- **Ekspor** (Export): Word, Markdown or JSON.
- **Send tasks**: add a destination under **Pengaturan → Integrasi** (GitHub, GitLab or webhook), then on the Task tab
  click **Kirim N task** (Send N tasks). Token and permission guide: [INTEGRATIONS.md](docs/INTEGRATIONS.md).

### Time zone

Default **WIB (Asia/Jakarta)**. Change it in **Pengaturan**; deadlines such as "tomorrow" are computed in this zone.

## 🏢 Shared server for teams

For an office: one server, many users, Google sign-in, each person sees only their own meetings (super admins see
all). The desktop app is then switched to **Server terpisah** (Remote server) mode.

**No build needed:** a prebuilt image is published on GHCR. In Portainer paste [`docker-compose.image.yml`](docker-compose.image.yml) (CPU) or [`docker-compose.image-gpu.yml`](docker-compose.image-gpu.yml) (NVIDIA GPU) as a stack (or `docker compose -f <file> up -d`); details in [docs/INSTALL.md](docs/INSTALL.md).

```bash
# or build from source:
cp server/.env.example .env         # fill in PUBLIC_URL, Google OAuth keys and SUPERADMINS
docker compose up -d --build
```

**Google sign-in is implemented** (OIDC authorization code + PKCE) but so far tested only against a mock identity
provider, not real Google. Because the project is open source there are **no bundled Google credentials**: the
installer creates their own OAuth client in Google Cloud Console and supplies the Client ID/Secret through server
environment variables (not through the UI). Full steps, variables and the security model are in
**[docs/AUTH.md](docs/AUTH.md)**. Behind a reverse proxy, see the large-upload notes in
[docs/INSTALL.md](docs/INSTALL.md).

## 🧰 Troubleshooting

| Symptom | Cause and fix |
|---|---|
| SmartScreen blocks the installer | The beta installer is unsigned. **More info → Run anyway**. |
| "Engine not installed" | Finish **Step 3**, then **Uji mesin**. |
| Summary failed but transcript exists | Wrong API key or usage limit hit. The transcript is kept; click **Buat ulang ringkasan** (Regenerate summary) once fixed. |
| No meeting audio (microphone only) | Windows: make sure an active output device exists. Linux: install `pulseaudio-utils` / `pipewire-pulse`. |
| `Ctrl+Alt+R` does nothing | Conflicts with another app. Change it in Settings. |
| GPU out of memory | Rekamind automatically falls back to a lighter mode, then to CPU. Close other GPU apps. |
| Slow on an AMD/Intel GPU machine | Check **Uji mesin**: if it shows no GPU, the engine fell back to the CPU (update the graphics driver). Experimental engines may also be slower than expected. |

Backend log lives in the app data folder: `backend\logs\backend.log` (Windows: `%LOCALAPPDATA%\id.rekamind.desktop`;
on Linux the exact location is shown in Settings → backend folder).
When reporting a bug, **do not** attach recordings or API keys. Use the
[issue template](https://github.com/handokoaji/rekamind/issues/new/choose).

## ⚠️ Beta limitations

Stated plainly so you know what is being tested:

- **Installers are unsigned** (Windows will warn you).
- **Linux desktop (tray, global hotkey, audio capture) has not been tested on a real machine.** The backend and UI are
  tested on Linux; the desktop shell is only built in CI.
- **Windows**: tested on one PC (Windows 11, GTX 1080 Ti). Long recordings with the window closed, force-kill during
  recording, Word export in real Microsoft Word, and Credential Manager storage are still being tested manually.
- **GPU**: CPU and NVIDIA CUDA are supported; **Intel GPU is experimental** (OpenVINO, unverified in v2); AMD GPU (Vulkan) is experimental and unverified.
- **Real GitHub, GitLab, Google sign-in and S3/MinIO** have only been tested against mock/automated servers.
- **Quality** of transcripts, speaker separation and task extraction has not been measured across many kinds of
  audio. Review the output, especially names and deadlines.
- **Language:** the interface has Indonesian and English; the generated summary and tasks are Indonesian only. Messages coming from the server or the Rust recorder (e.g. some error texts) are not translated yet.
- The old v1 app (Tkinter) lives in git history and tags `v0.1.0` to `v0.3.0`; v2 is not compatible with it.

## 🗺️ Roadmap

Planned for the next releases (**not implemented yet**; listed so you know what to expect, and in no firm order):

- **Intel GPU**: experimental support is implemented (OpenVINO); it graduates once verified on real hardware.
- **AMD GPU**: experimental support is implemented (Vulkan / whisper.cpp) and is being tested on a Ryzen AI 7 350. Older/smaller iGPUs such as the Vega in a Ryzen 5 5600G are not targeted (little benefit expected). **Volunteer testers with other AMD machines welcome** (open an issue).
- **More interface languages** beyond Indonesian and English, and a choice of output language for summaries and tasks.

Machines without a supported GPU run on the CPU (see [GPU support](#gpu-support)).

## 🛠️ For developers

```bash
pip install -e "server[dev]" && pytest server          # backend
cd web && npm ci && npm test && npm run build          # interface
cd recorder && cargo test                              # Rust recorder
python scripts/build_desktop.py                        # local installer (Windows: nsis, Linux: deb)
```

Architecture: [docs/v2/ARCHITECTURE.md](docs/v2/ARCHITECTURE.md) (Indonesian) · Releasing: [docs/RELEASING.md](docs/RELEASING.md) ·
Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) · Security: [SECURITY.md](SECURITY.md) ·
Changelog: [CHANGELOG.md](CHANGELOG.md)

## License

[MIT](LICENSE). Third-party libraries and models have their own licences (e.g. the pyannote models require accepting
terms on Hugging Face).
