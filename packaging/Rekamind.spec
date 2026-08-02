# packaging/Rekamind.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for pkg in ("torch", "ctranslate2", "faster_whisper", "pyannote.audio", "openvino", "optimum"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["../app/main.py"],
    pathex=["../"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Rekamind",
    console=False,  # --windowed: no console window for a Tk GUI app
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="Rekamind",
)
