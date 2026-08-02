<!-- packaging/README.md -->
# Building the Windows installer

0. **Install CUDA-enabled torch before anything else**, in a clean venv:
   `pip install torch==2.13.0+cu126 --index-url https://download.pytorch.org/whl/cu126`
   then `pip install -e .`. PyPI's default torch has no CUDA support compiled
   in and `pyproject.toml` cannot pin a per-package index URL, so skipping this
   produces a build where the diarizer can only ever run on CPU (see
   `app.main.diarizer_device`). torch's own `lib/` is also where ctranslate2
   finds the cuBLAS/cuDNN DLLs it needs for CUDA transcription -- this one
   install is what makes the whole GPU path work. It is ~4GB of the ~1.8GB
   installer; a build done without it lands around 500MB and is CPU/OpenVINO
   only.
1. `pip install pyinstaller`
2. Download a static `ffmpeg.exe` build (e.g. from gyan.dev's builds page)
   and place it at `packaging/ffmpeg/ffmpeg.exe`.
3. From `packaging/`, run: `pyinstaller Rekamind.spec`
4. Copy `packaging/ffmpeg/` into `dist/Rekamind/ffmpeg/` so
   `app.main.prepend_bundled_ffmpeg_to_path()` finds it next to the built
   executable at runtime.
5. Proceed to the Inno Setup step (see `packaging/installer.iss`) to
   produce the final `rekamind-<version>.exe`.

Model weights are NOT bundled -- they download automatically the first
time Transkrip/Ringkasan is used, exactly like running from source.
