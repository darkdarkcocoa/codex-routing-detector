@echo off
rem Build dist\codex-routing-detector.exe (single file, no console window) with PyInstaller.
rem Requires Python 3.8+ on PATH. The resulting exe still needs a signed-in Codex install to run checks.
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul || (
  echo Python 3.8 or newer is required on PATH to build the exe.
  pause
  exit /b 1
)
python -m pip install --upgrade pyinstaller cryptography pywebview || (echo pip install failed. & pause & exit /b 1)
rem codex-routing-detector.spec: one file, no console, docs\icon.ico, entry codex_routing_webui.py
rem (the pywebview window; the tkinter window is bundled as its fallback).
python -m PyInstaller --noconfirm --clean codex-routing-detector.spec || (echo PyInstaller failed. & pause & exit /b 1)
echo.
echo Built: %~dp0dist\codex-routing-detector.exe
pause
