@echo off
rem Jalankan Rekamind pakai venv repo ini (tanpa perlu activate manual).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo venv tidak ditemukan di .venv -- buat dulu: python -m venv .venv ^&^& .venv\Scripts\pip install -e .
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m app.main
