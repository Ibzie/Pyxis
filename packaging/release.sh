#!/usr/bin/env bash
set -euo pipefail

# ── Create a GitHub Release and upload binaries ───────────────────────────
# Usage: ./packaging/release.sh [version]
# Default version: 1.0.0
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated: gh auth login
#   - Build artifacts in dist/ (run build_linux.sh / build_windows.bat first)
#   - All changes committed and pushed to main

VERSION="${1:-1.0.0}"
TAG="v${VERSION}"

cd "$(dirname "$0")/.."

# Check gh CLI
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI (gh) not installed."
    echo "  Install: https://cli.github.com/"
    echo "  Then:    gh auth login"
    exit 1
fi

if ! gh auth status &>/dev/null; then
    echo "ERROR: Not authenticated with GitHub CLI."
    echo "  Run: gh auth login"
    exit 1
fi

# Check for build artifacts
if [ ! -d "dist" ] || [ -z "$(ls -A dist/ 2>/dev/null)" ]; then
    echo "ERROR: No build artifacts in dist/"
    echo "  Run: ./packaging/build_linux.sh  (and build_windows.bat on Windows)"
    exit 1
fi

echo "=== Creating GitHub Release $TAG ==="

# Create git tag
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "  Tag $TAG already exists"
else
    git tag "$TAG"
    git push origin "$TAG"
    echo "  Created and pushed tag $TAG"
fi

# Create release + upload assets
RELEASE_NOTES="## Pyxis v${VERSION}

### Downloads
- **Linux**: \`Pyxis-${VERSION}-x86_64.AppImage\` — single file, no install needed
  - \`chmod +x Pyxis-${VERSION}-x86_64.AppImage && ./Pyxis-${VERSION}-x86_64.AppImage\`
- **Windows**: \`Pyxis.exe\` — single portable executable, no install needed
  - Double-click to run

### Features
- PDF reader with AI-powered notes
- Multimodal Gemma 4 model (text + image understanding)
- Accessibility mode for blind users (TTS narration + image descriptions)
- RAG-based Q\&A with page citations
- WYSIWYG Markdown notes panel
- 100\% local — your data never leaves your machine

### First run
The app downloads the AI model (~5 GB) and TTS voice (~65 MB) on first use.
If you have an NVIDIA GPU, it auto-downloads the CUDA build for faster AI.
"

gh release create "$TAG" \
    --title "Pyxis v${VERSION}" \
    --notes "$RELEASE_NOTES" \
    --latest

# Upload assets
echo "--- Uploading assets..."
for f in dist/*.AppImage dist/*.exe dist/*.pkg dist/*.dmg; do
    if [ -f "$f" ]; then
        echo "  Uploading $(basename "$f") ($(du -sh "$f" | cut -f1))..."
        gh release upload "$TAG" "$f" --clobber
    fi
done

echo ""
echo "=== Release created ==="
REPO_URL=$(gh repo view --json url -q .url)
echo "  Download: ${REPO_URL}/releases/tag/${TAG}"
