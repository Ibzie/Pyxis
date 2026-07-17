@echo off
REM ── Build AI-PDF portable EXE for Windows ───────────────────────────────
REM Produces: dist\AI-PDF.exe  (single portable executable, no install needed)
REM
REM Prerequisites:
REM   - Python 3.10+ venv at .venv\ with requirements.txt installed
REM   - PyInstaller: pip install pyinstaller
REM   - CPU llama-cpp-python is fine — the app auto-downloads CUDA on first run

cd /d "%~dp0\.."
echo === AI-PDF Windows EXE Build ===

REM Clean previous builds
if exist build\ rmdir /s /q build
if exist dist\AI-PDF.exe del /q dist\AI-PDF.exe
if not exist dist mkdir dist

REM Run PyInstaller in onefile mode
echo --- Running PyInstaller (onefile)...
set AIPDF_ONEFILE=1
python -m PyInstaller packaging\ai-pdf.spec --noconfirm --clean
set AIPDF_ONEFILE=

if not exist "dist\AI-PDF.exe" (
    echo ERROR: dist\AI-PDF.exe not created — build failed
    exit /b 1
)

for %%I in (dist\AI-PDF.exe) do set SIZE=%%~zI
echo.
echo === Build complete ===
echo   Output: dist\AI-PDF.exe
echo.
echo   To run:   Double-click AI-PDF.exe
echo   To install: Copy AI-PDF.exe to any folder (e.g. Desktop or Program Files)
echo   No installation step needed — it's a single portable executable.
