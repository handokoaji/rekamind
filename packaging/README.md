<!-- packaging/README.md -->
# Building the Windows installer

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
