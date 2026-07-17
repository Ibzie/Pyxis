# AI-PDF Packaging

Build scripts and installer configs for Linux, Windows, and macOS.

## Quick start

### Linux
```sh
# From the project root:
pip install -r requirements.txt
pip install pyinstaller
./packaging/build_linux.sh
# → dist/AI-PDF-linux-x64.tar.gz

# Install:
./packaging/install_linux.sh dist/AI-PDF-linux-x64.tar.gz
# → ~/.local/share/ai-pdf/app/AI-PDF
# → ~/.local/bin/ai-pdf (launcher)
# → desktop entry in applications menu
```

### Windows
```bat
pip install -r requirements.txt
pip install pyinstaller
packaging\build_windows.bat
:: → dist\AI-PDF\ (raw bundle)
:: → packaging\Output\AI-PDF-Setup.exe (if Inno Setup installed)
```
Install [Inno Setup 6+](https://jrsoftware.org/isdl.php) to create the installer.

### macOS
```sh
# Metal-enabled llama-cpp-python (GPU acceleration built-in):
CMAKE_ARGS="-DGGML_METAL=on" pip install --force-reinstall llama-cpp-python
pip install -r requirements.txt
pip install pyinstaller
./packaging/build_macos.sh
# → dist/AI-PDF.app
# → dist/AI-PDF.pkg
```

## GPU acceleration

The packaged app ships with a **CPU-only** `llama-cpp-python` build for
universality. On first run, if an NVIDIA GPU is detected (Linux/Windows),
the app downloads a CUDA-built `libllama` shared library (~15 MB) into
`~/.local/share/ai-pdf/native/` and prompts the user to restart. After
restart, AI inference uses the GPU automatically.

**macOS** uses Metal acceleration, which is built into the default
`llama-cpp-python` wheel — no extra download needed.

### Hosting the CUDA libraries

The CUDA `libllama` binaries are hosted as HuggingFace release assets in
the `ai-pdf/native-libs` repository. To build and upload them:

```sh
# Linux CUDA build
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall llama-cpp-python
# Extract the shared library:
python -c "import llama_cpp, pathlib; p=pathlib.Path(llama_cpp.__file__).parent; print(p)"
# Find libllama.so in that directory, rename to libllama-cuda12-linux-x64.so
# Upload to HuggingFace: ai-pdf/native-libs

# Windows CUDA build (on a Windows machine with CUDA Toolkit)
set CMAKE_ARGS=-DGGML_CUDA=on
pip install --force-reinstall llama-cpp-python
# Find llama.dll, rename to llama-cuda-win-x64.dll
# Upload to HuggingFace: ai-pdf/native-libs
```

## App icon

The icon source is `packaging/icons/ai-pdf.svg`. Pre-generated formats:
- `ai-pdf.png` (256×256) — Linux
- `ai-pdf.ico` (multi-res) — Windows

To generate the macOS `.icns` (must be done on macOS):
```sh
mkdir ai-pdf.iconset
sips -z 16 16     packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_16x16.png
sips -z 32 32     packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_16x16@2x.png
sips -z 32 32     packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_32x32.png
sips -z 64 64     packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_32x32@2x.png
sips -z 128 128   packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_128x128.png
sips -z 256 256   packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_128x128@2x.png
sips -z 256 256   packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_256x256.png
sips -z 512 512   packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_256x256@2x.png
sips -z 512 512   packaging/icons/ai-pdf.png --out ai-pdf.iconset/icon_512x512.png
cp packaging/icons/ai-pdf.png ai-pdf.iconset/icon_512x512@2x.png
iconutil -c icns ai-pdf.iconset -o packaging/icons/ai-pdf.icns
rm -rf ai-pdf.iconset
```

## Data directories

The app stores all user data in OS-specific locations:
| Platform | Path |
|---|---|
| Linux | `~/.local/share/ai-pdf/` |
| macOS | `~/Library/Application Support/ai-pdf/` |
| Windows | `%APPDATA%\ai-pdf\` |

Subdirectories:
- `notes/<pdf-name>/` — per-PDF notes, highlights, captures, annotations
- `models/` — HuggingFace model cache (GGUF + mmproj)
- `voices/` — Piper TTS voice files
- `native/` — CUDA-built libllama (auto-downloaded)
- `ai.log` — rotating log file

## Bundle size

The packaged app is ~300 MB (uncompressed), primarily from:
- PyQt6: ~80 MB
- PyMuPDF: ~30 MB
- llama-cpp-python: ~10 MB (CPU) or ~50 MB (with CUDA)
- onnxruntime + piper-tts: ~60 MB
- Python runtime + stdlib: ~40 MB

Compressed (tar.gz / LZMA): ~120-150 MB.
