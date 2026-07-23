#!/usr/bin/env bash
set -euo pipefail

# ── Build Pyxis AppImage for Linux ────────────────────────────────────────
# Produces: dist/Pyxis-x86_64.AppImage
#
# Prerequisites:
#   - Python 3.10+ venv at .venv/ with requirements.txt + pyinstaller installed
#   - appimagetool downloaded automatically if missing
#
# The AppImage is a single executable file that mounts via FUSE and runs
# without installation. Users just: chmod +x Pyxis-x86_64.AppImage && ./Pyxis-x86_64.AppImage

cd "$(dirname "$0")/.."
echo "=== Pyxis Linux AppImage Build ==="

# ── Pick a Python interpreter ──────────────────────────────────────────────
# Prefer a local venv, fall back to the system python (CI environments).
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi
echo "  Using interpreter: $PY ($($PY --version 2>&1))"

# Clean previous builds
rm -rf build/ dist/Pyxis/ dist/AppDir/ dist/Pyxis-*.AppImage
mkdir -p dist

# ── Step 1: PyInstaller onedir build ──────────────────────────────────────
echo "--- Running PyInstaller (onedir)..."
"$PY" -m PyInstaller packaging/pyxis.spec --noconfirm --clean

if [ ! -d "dist/Pyxis" ]; then
    echo "ERROR: dist/Pyxis/ not created — PyInstaller build failed"
    exit 1
fi
BUNDLE_SIZE=$(du -sh dist/Pyxis/ | cut -f1)
echo "  Bundle: dist/Pyxis/ ($BUNDLE_SIZE)"

# ── Step 2: Assemble AppDir ───────────────────────────────────────────────
echo "--- Assembling AppDir..."
APPDIR="dist/AppDir"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy the PyInstaller bundle into usr/bin/
cp -r dist/Pyxis "$APPDIR/usr/bin/Pyxis"

# Copy AppRun (entry point) and desktop file
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp packaging/pyxis.desktop "$APPDIR/pyxis.desktop"

# Copy icon
if [ -f "packaging/icons/pyxis.png" ]; then
    cp packaging/icons/pyxis.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/pyxis.png"
    # Also place at root for AppImage discovery
    cp packaging/icons/pyxis.png "$APPDIR/pyxis.png"
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
VERSION="${PYXIS_VERSION:-1.0.0}"
ARCH=$(uname -m | sed 's/x86_64/x86_64/' | sed 's/aarch64/aarch64/')
OUTPUT="dist/Pyxis-${VERSION}-${ARCH}.AppImage"

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
echo "  To install: mv $OUTPUT ~/.local/bin/pyxis (or any PATH dir)"
