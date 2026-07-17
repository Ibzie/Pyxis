#!/usr/bin/env bash
set -euo pipefail

# ── Build AI-PDF for Linux ────────────────────────────────────────────────
# Produces:  dist/AI-PDF/                 (onedir bundle)
#            AI-PDF-linux-x64.tar.gz      (distributable tarball)
#
# Run on a Linux x86_64 machine with:
#   - Python 3.10+ venv at .venv/
#   - requirements.txt installed (CPU llama-cpp-python is fine — the app
#     auto-downloads the CUDA lib on first run if a GPU is detected)
#   - PyInstaller installed (pip install pyinstaller)

cd "$(dirname "$0")/.."
echo "=== AI-PDF Linux Build ==="

# Clean previous builds
rm -rf build/ dist/AI-PDF/
mkdir -p dist

# Run PyInstaller
echo "--- Running PyInstaller..."
python -m PyInstaller packaging/ai-pdf.spec --noconfirm --clean

# Verify the bundle exists
if [ ! -d "dist/AI-PDF" ]; then
    echo "ERROR: dist/AI-PDF/ not created — build failed"
    exit 1
fi

# Quick smoke test (headless)
echo "--- Smoke test (headless)..."
QT_QPA_PLATFORM=offscreen ./dist/AI-PDF/AI-PDF --help 2>/dev/null || true

# Create tarball
echo "--- Creating tarball..."
tar czf dist/AI-PDF-linux-x64.tar.gz -C dist AI-PDF
SIZE=$(du -sh dist/AI-PDF-linux-x64.tar.gz | cut -f1)
echo ""
echo "=== Build complete ==="
echo "  Bundle:  dist/AI-PDF/"
echo "  Tarball: dist/AI-PDF-linux-x64.tar.gz ($SIZE)"
echo ""
echo "To install: ./packaging/install_linux.sh dist/AI-PDF-linux-x64.tar.gz"
