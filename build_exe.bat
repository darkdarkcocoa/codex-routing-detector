@echo off
rem Build dist\codex-routing-detector.exe (single file, no console window) with PyInstaller.
rem Requires Python 3.8+ on PATH. The resulting exe still needs a signed-in Codex install to run checks.
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul || (
  echo Python 3.8 or newer is required on PATH to build the exe.
  pause
  exit /b 1
)
python -m pip install --upgrade pyinstaller cryptography || (echo pip install pyinstaller failed. & pause & exit /b 1)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name codex-routing-detector codex_routing_detector_gui.py || (echo PyInstaller failed. & pause & exit /b 1)
echo.
echo Built: %~dp0dist\codex-routing-detector.exe
pause
