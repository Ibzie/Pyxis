#!/usr/bin/env bash
set -euo pipefail

# ── Build AI-PDF AppImage for Linux ───────────────────────────────────────
# Produces: dist/AI-PDF-x86_64.AppImage
#
# Prerequisites:
#   - Python 3.10+ venv at .venv/ with requirements.txt + pyinstaller installed
#   - appimagetool downloaded automatically if missing
#
# The AppImage is a single executable file that mounts via FUSE and runs
# without installation. Users just: chmod +x AI-PDF-x86_64.AppImage && ./AI-PDF-x86_64.AppImage

cd "$(dirname "$0")/.."
echo "=== AI-PDF Linux AppImage Build ==="

# Clean previous builds
rm -rf build/ dist/AI-PDF/ dist/AppDir/ dist/AI-PDF-x86_64.AppImage
mkdir -p dist

# ── Step 1: PyInstaller onedir build ──────────────────────────────────────
echo "--- Running PyInstaller (onedir)..."
.venv/bin/python -m PyInstaller packaging/ai-pdf.spec --noconfirm --clean

if [ ! -d "dist/AI-PDF" ]; then
    echo "ERROR: dist/AI-PDF/ not created — PyInstaller build failed"
    exit 1
fi
BUNDLE_SIZE=$(du -sh dist/AI-PDF/ | cut -f1)
echo "  Bundle: dist/AI-PDF/ ($BUNDLE_SIZE)"

# ── Step 2: Assemble AppDir ───────────────────────────────────────────────
echo "--- Assembling AppDir..."
APPDIR="dist/AppDir"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy the PyInstaller bundle into usr/bin/
cp -r dist/AI-PDF "$APPDIR/usr/bin/AI-PDF"

# Copy AppRun (entry point) and desktop file
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp packaging/ai-pdf.desktop "$APPDIR/ai-pdf.desktop"

# Copy icon
if [ -f "packaging/icons/ai-pdf.png" ]; then
    cp packaging/icons/ai-pdf.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-pdf.png"
    # Also place at root for AppImage discovery
    cp packaging/icons/ai-pdf.png "$APPDIR/ai-pdf.png"
else
    echo "  Warning: icon not found — AppImage will use default icon"
fi

# ── Step 3: Download appimagetool if missing ──────────────────────────────
TOOL="$HOME/.local/bin/appimagetool"
if [ ! -x "$TOOL" ]; then
    echo "--- Downloading appimagetool..."
    mkdir -p "$(dirname "$TOOL")"
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    else
        URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-aarch64.AppImage"
    fi
    curl -fsSL "$URL" -o "$TOOL"
    chmod +x "$TOOL"
    echo "  Downloaded appimagetool to $TOOL"
fi

# ── Step 4: Build AppImage ────────────────────────────────────────────────
echo "--- Building AppImage..."
VERSION="${AIPDF_VERSION:-1.0.0}"
ARCH=$(uname -m | sed 's/x86_64/x86_64/' | sed 's/aarch64/aarch64/')
OUTPUT="dist/AI-PDF-${VERSION}-${ARCH}.AppImage"

# appimagetool needs ARCH env var
export ARCH
"$TOOL" "$APPDIR" "$OUTPUT" --no-appstream

if [ ! -f "$OUTPUT" ]; then
    echo "ERROR: AppImage not created"
    exit 1
fi

APPIMAGE_SIZE=$(du -sh "$OUTPUT" | cut -f1)
echo ""
echo "=== Build complete ==="
echo "  AppImage: $OUTPUT ($APPIMAGE_SIZE)"
echo ""
echo "  To run:   chmod +x $OUTPUT && ./$OUTPUT"
echo "  To install: mv $OUTPUT ~/.local/bin/ai-pdf (or any PATH dir)"
