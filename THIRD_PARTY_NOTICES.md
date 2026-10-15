# Third-party notices / Pemberitahuan pihak ketiga

Rekamind itself is licensed under **AGPL-3.0-or-later** (see [LICENSE](LICENSE)). It uses, or downloads at the user's
request, the third-party software and models below. They keep their own licences. This list is a good-faith summary,
not legal advice; "verified" means the licence was checked at the source on 2026-10-15, "not verified" means it is stated
from general knowledge and should be confirmed before relying on it.

*Rekamind sendiri berlisensi **AGPL-3.0-or-later**. Perangkat lunak dan model pihak ketiga di bawah ini tetap memakai
lisensinya masing-masing. Daftar ini ringkasan itikad baik, bukan nasihat hukum.*

## Models downloaded by the user (not part of Rekamind's code)

| Model | Licence | Status | Attribution |
|---|---|---|---|
| `pyannote/speaker-diarization-community-1` | CC-BY-4.0 | verified (Hugging Face model card) | pyannote, <https://huggingface.co/pyannote/speaker-diarization-community-1> |
| `pyannote/wespeaker-voxceleb-resnet34-LM` | CC-BY-4.0 | verified (Hugging Face model card) | pyannote / Wespeaker, <https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM> |
| `pyannote/speaker-diarization-3.1` | MIT | verified (Hugging Face model card) | pyannote |
| `pyannote/segmentation-3.0` | MIT | verified (Hugging Face model card) | pyannote |
| OpenAI Whisper (`large-v3` and smaller; ggml quantised files for whisper.cpp) | MIT | not verified | OpenAI; ggml conversions by the whisper.cpp project |

The pyannote models are gated on Hugging Face: each user accepts the terms and supplies their own token (see
[docs/API_KEYS.md](docs/API_KEYS.md)). CC-BY-4.0 requires crediting the authors, which this file does.

## Native program downloaded on demand

| Component | Licence | Status |
|---|---|---|
| `whisper.cpp` (`whisper-cli`, built by this project's CI with Vulkan) | MIT, Copyright (c) the whisper.cpp / ggml authors | verified: the licence text ships next to the binary as `LICENSE-whisper.cpp` |

## Code dependencies

| Component | Licence | Status |
|---|---|---|
| pyannote.audio | MIT, Copyright (c) 2020 CNRS | verified (GitHub `LICENSE`) |
| PyAV (`av`) | BSD-3-Clause | verified (PyPI). Its wheels bundle FFmpeg; **the FFmpeg licence variant (LGPL or GPL) of the bundled build is not verified** |
| faster-whisper, FastAPI, Uvicorn, SQLAlchemy, Alembic, PyJWT, Pydantic, httpx, NumPy, python-docx, boto3, asyncpg, PyTorch, OpenVINO / optimum-intel | MIT, BSD or Apache-2.0 | not verified |
| React, Radix UI, TanStack, Tailwind CSS, Sonner, lucide-react | MIT or ISC | not verified |
| Inter font (`@fontsource-variable/inter`) | SIL Open Font License 1.1 | not verified |
| Tauri, `keyring`, `wasapi`, `ureq`, `ctrlc`, `webbrowser` and other Rust crates | MIT and/or Apache-2.0 | not verified |

MIT, BSD and Apache-2.0 components are compatible with AGPL-3.0-or-later.

## Proprietary runtime libraries (NVIDIA GPU image only)

The NVIDIA GPU server image and the NVIDIA engine pack use `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`, which are under
NVIDIA's own licence terms, not AGPL. The desktop app downloads them to the user's machine on request. The published
`-cuda` Docker image contains them, so NVIDIA's redistribution terms apply to that image.
