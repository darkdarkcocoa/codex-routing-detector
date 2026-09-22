@echo off
rem Launch the codex-routing-detector window with the Python that is on PATH.
rem Use dist\codex-routing-detector.exe instead if you built the standalone executable.
cd /d "%~dp0"
rem `where python` is not enough: Windows ships Store stubs named python.exe that only open the
rem Microsoft Store, and an old Python would fail silently under pythonw. Ask the interpreter.
pythonw -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && (start "" pythonw "%~dp0codex_routing_detector_gui.py" & exit /b 0)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && (start "" python "%~dp0codex_routing_detector_gui.py" & exit /b 0)
echo Python 3.8 or newer is required. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, or use dist\codex-routing-detector.exe.
pause
