@echo off
REM ── Build Pyxis portable EXE for Windows ────────────────────────────────
REM Produces: dist\Pyxis-<version>-x64.exe when PYXIS_VERSION is set (CI
REM passes the pushed git tag), otherwise dist\Pyxis.exe
REM
REM Prerequisites:
REM   - Python 3.10+ venv at .venv\ with requirements.txt installed
REM   - PyInstaller: pip install pyinstaller
REM   - For GPU builds, install the CUDA llama-cpp-python wheel first (see README)

cd /d "%~dp0\.."
echo === Pyxis Windows EXE Build ===

REM Clean previous builds
if exist build\ rmdir /s /q build
if exist dist\Pyxis.exe del /q dist\Pyxis.exe
if exist dist\Pyxis-*-x64.exe del /q dist\Pyxis-*-x64.exe
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
if defined PYXIS_VERSION (
    ren "dist\Pyxis.exe" "Pyxis-%PYXIS_VERSION%-x64.exe"
    echo === Build complete ===
    echo   Output: dist\Pyxis-%PYXIS_VERSION%-x64.exe
) else (
    echo === Build complete ===
    echo   Output: dist\Pyxis.exe
)
echo.
echo   To run:   Double-click the exe
echo   To install: Copy it to any folder (e.g. Desktop or Program Files)
echo   No installation step needed — it's a single portable executable.
