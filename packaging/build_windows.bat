@echo off
REM ── Build AI-PDF for Windows ────────────────────────────────────────────
REM Produces:  dist\AI-PDF\                     (onedir bundle)
REM             packaging\Output\AI-PDF-Setup.exe (Inno Setup installer)
REM
REM Prerequisites:
REM   - Python 3.10+ venv at .venv\
REM   - requirements.txt installed (CPU llama-cpp-python)
REM   - PyInstaller: pip install pyinstaller
REM   - Inno Setup 6+ (for installer creation): https://jrsoftware.org/isdl.php

cd /d "%~dp0\.."
echo === AI-PDF Windows Build ===

REM Clean previous builds
if exist build\ rmdir /s /q build
if exist dist\AI-PDF\ rmdir /s /q dist\AI-PDF
if not exist dist mkdir dist

REM Run PyInstaller
echo --- Running PyInstaller...
python -m PyInstaller packaging\ai-pdf.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)

REM Verify
if not exist "dist\AI-PDF\AI-PDF.exe" (
    echo ERROR: dist\AI-PDF\AI-PDF.exe not created
    exit /b 1
)

REM Create installer with Inno Setup (if available)
echo --- Creating installer...
where iscc >nul 2>nul
if errorlevel 1 (
    echo WARNING: Inno Setup (iscc) not found in PATH.
    echo   Install from https://jrsoftware.org/isdl.php to create the installer.
    echo   The raw bundle is at dist\AI-PDF\
    exit /b 0
)

iscc packaging\ai-pdf.iss
if errorlevel 1 (
    echo WARNING: Inno Setup compilation failed. Raw bundle is at dist\AI-PDF\
    exit /b 0
)

echo.
echo === Build complete ===
echo   Bundle:    dist\AI-PDF\
echo   Installer: packaging\Output\AI-PDF-Setup.exe
echo.
echo   To install: Run AI-PDF-Setup.exe
