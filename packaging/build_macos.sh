#!/usr/bin/env bash
set -euo pipefail

# ── Build AI-PDF for macOS ────────────────────────────────────────────────
# Produces:  dist/AI-PDF.app/        (app bundle)
#            AI-PDF.pkg              (installer package)
#
# Prerequisites:
#   - macOS with Python 3.10+ venv at .venv/
#   - requirements.txt installed with Metal-enabled llama-cpp-python:
#       CMAKE_ARGS="-DGGML_METAL=on" pip install --force-reinstall llama-cpp-python
#   - PyInstaller: pip install pyinstaller

cd "$(dirname "$0")/.."
echo "=== AI-PDF macOS Build ==="

# Clean previous builds
rm -rf build/ dist/AI-PDF/ dist/AI-PDF.app
mkdir -p dist

# Run PyInstaller
echo "--- Running PyInstaller..."
python -m PyInstaller packaging/ai-pdf.spec --noconfirm --clean

# Verify
if [ ! -d "dist/AI-PDF" ]; then
    echo "ERROR: dist/AI-PDF/ not created — build failed"
    exit 1
fi

# Wrap in .app bundle
echo "--- Creating .app bundle..."
APP_DIR="dist/AI-PDF.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# Move the onedir contents into the app bundle
cp -R dist/AI-PDF/* "$APP_DIR/Contents/MacOS/"

# Copy Info.plist
cp packaging/Info.plist "$APP_DIR/Contents/Info.plist"

# Copy icon if available
if [ -f "packaging/icons/ai-pdf.icns" ]; then
    cp packaging/icons/ai-pdf.icns "$APP_DIR/Contents/Resources/ai-pdf.icns"
fi

# Make executable
chmod +x "$APP_DIR/Contents/MacOS/AI-PDF"

# Create .pkg installer
echo "--- Creating .pkg installer..."
pkgbuild \
    --root "$APP_DIR" \
    --install-location "/Applications/AI-PDF.app" \
    --identifier "com.ai-pdf.app" \
    --version "1.0.0" \
    dist/AI-PDF.pkg

SIZE=$(du -sh dist/AI-PDF.pkg | cut -f1)
echo ""
echo "=== Build complete ==="
echo "  App bundle:  dist/AI-PDF.app/"
echo "  Installer:   dist/AI-PDF.pkg ($SIZE)"
echo ""
echo "  To install:  Open AI-PDF.pkg and follow the wizard."
echo "  To run:      Double-click AI-PDF.app in Applications."
