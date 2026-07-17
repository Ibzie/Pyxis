@echo off
REM ── Build Pyxis portable EXE for Windows ────────────────────────────────
REM Produces: dist\Pyxis.exe  (single portable executable, no install needed)
REM
REM Prerequisites:
REM   - Python 3.10+ venv at .venv\ with requirements.txt installed
REM   - PyInstaller: pip install pyinstaller
REM   - CPU llama-cpp-python is fine — the app auto-downloads CUDA on first run

cd /d "%~dp0\.."
echo === Pyxis Windows EXE Build ===

REM Clean previous builds
if exist build\ rmdir /s /q build
if exist dist\Pyxis.exe del /q dist\Pyxis.exe
if not exist dist mkdir dist

REM Run PyInstaller in onefile mode
echo --- Running PyInstaller (onefile)...
set PYXIS_ONEFILE=1
python -m PyInstaller packaging\pyxis.spec --noconfirm --clean
set PYXIS_ONEFILE=

if not exist "dist\Pyxis.exe" (
    echo ERROR: dist\Pyxis.exe not created — build failed
    exit /b 1
)

for %%I in (dist\Pyxis.exe) do set SIZE=%%~zI
echo.
echo === Build complete ===
echo   Output: dist\Pyxis.exe
echo.
echo   To run:   Double-click Pyxis.exe
echo   To install: Copy Pyxis.exe to any folder (e.g. Desktop or Program Files)
echo   No installation step needed — it's a single portable executable.
