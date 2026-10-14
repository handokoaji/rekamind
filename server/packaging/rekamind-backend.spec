import os
# PyInstaller spec for the desktop backend. Build: `pyinstaller --noconfirm packaging/rekamind-backend.spec` (from server/)
# onedir, not onefile: onefile unpacks ~100 MB on every launch, which is exactly the latency and the
# antivirus attention a backend that starts on demand cannot afford.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("rekamind_server")
    + collect_submodules("sqlalchemy.dialects.sqlite")
    + collect_submodules("pip")  # the engine pack is installed with pip running inside this very binary
    + ["aiosqlite", "multipart", "python_multipart", "email.mime.text"]
)
datas = (
    # Alembic loads env.py and each revision *by file path*, so they must exist as real files, not only
    # inside the frozen archive.
    [(os.path.join(SPECPATH, "..", "rekamind_server", "migrations"), "rekamind_server/migrations")]
    + collect_data_files("alembic")
    + collect_data_files("pip")
    + collect_data_files("certifi")
)
# The ML stack is never frozen in: it is installed on demand (see rekamind_server/enginepack.py).
excludes = ["torch", "torchaudio", "pyannote", "faster_whisper", "ctranslate2", "onnxruntime", "tkinter",
            "pytest", "moto", "boto3", "botocore", "asyncpg"]

a = Analysis([os.path.join(SPECPATH, "..", "sidecar_main.py")], pathex=[os.path.join(SPECPATH, "..")], datas=datas, hiddenimports=hidden, excludes=excludes)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="rekamind-backend", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="rekamind-backend", upx=False)
