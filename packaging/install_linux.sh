#!/usr/bin/env bash
set -euo pipefail

# ── Install AI-PDF on Linux ───────────────────────────────────────────────
# Usage:  ./install_linux.sh [tarball]
# Default tarball: dist/AI-PDF-linux-x64.tar.gz
#
# Installs to:    ~/.local/share/ai-pdf/app/
# Symlink:        ~/.local/bin/ai-pdf
# Desktop entry:  ~/.local/share/applications/ai-pdf.desktop
# Icon:           ~/.local/share/icons/hicolor/256x256/apps/ai-pdf.png

TARBALL="${1:-dist/AI-PDF-linux-x64.tar.gz}"
INSTALL_DIR="$HOME/.local/share/ai-pdf/app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

cd "$(dirname "$0")/.."

if [ ! -f "$TARBALL" ]; then
    echo "ERROR: Tarball not found: $TARBALL"
    echo "Run packaging/build_linux.sh first."
    exit 1
fi

echo "=== Installing AI-PDF ==="

# Stop any running instance
pkill -f "AI-PDF/AI-PDF" 2>/dev/null || true

# Extract
echo "--- Extracting to $INSTALL_DIR..."
rm -rf "$INSTALL_DIR"
mkdir -p "$(dirname "$INSTALL_DIR")"
tar xzf "$TARBALL" -C "$(dirname "$INSTALL_DIR")"
mv "$(dirname "$INSTALL_DIR")/AI-PDF" "$INSTALL_DIR"

# Create launcher symlink
echo "--- Creating launcher..."
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/ai-pdf" << 'LAUNCHER'
#!/usr/bin/env bash
exec "$(dirname "$(readlink -f "$0")")/../share/ai-pdf/app/AI-PDF" "$@"
LAUNCHER
chmod +x "$BIN_DIR/ai-pdf"

# Desktop entry
echo "--- Creating desktop entry..."
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/ai-pdf.desktop" << EOF
[Desktop Entry]
Type=Application
Name=AI-PDF
Comment=PDF reader with AI notes and accessibility
Exec=$BIN_DIR/ai-pdf %f
Icon=ai-pdf
Terminal=false
Categories=Office;Viewer;
MimeType=application/pdf;
EOF

# Icon (use bundled icon if available, else skip)
if [ -f "packaging/icons/ai-pdf.png" ]; then
    mkdir -p "$ICON_DIR"
    cp packaging/icons/ai-pdf.png "$ICON_DIR/ai-pdf.png"
    echo "--- Icon installed."
else
    echo "--- Warning: packaging/icons/ai-pdf.png not found — no icon installed."
fi

# Update desktop database (may not exist in minimal environments)
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "=== Installation complete ==="
echo "  Run from terminal:     ai-pdf"
echo "  Run from app menu:     Search 'AI-PDF'"
echo "  Open a PDF:            ai-pdf /path/to/file.pdf"
echo ""
echo "  Data directory:        ~/.local/share/ai-pdf/"
echo "  Notes saved to:        ~/.local/share/ai-pdf/notes/<pdf-name>/"
