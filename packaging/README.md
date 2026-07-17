# AI-PDF Packaging

Build scripts for Linux (AppImage) and Windows (portable EXE).

## Quick start

### Linux — AppImage
```sh
# From the project root:
pip install -r requirements.txt
pip install pyinstaller
./packaging/build_linux.sh
# → dist/AI-PDF-1.0.0-x86_64.AppImage
```
Run: `chmod +x dist/AI-PDF-*.AppImage && ./dist/AI-PDF-*.AppImage`

Install (optional): `mv dist/AI-PDF-*.AppImage ~/.local/bin/ai-pdf`

The AppImage is a single self-contained executable — no installation,
no root permissions, no dependencies. It mounts via FUSE and runs.

### Windows — Portable EXE
```bat
pip install -r requirements.txt
pip install pyinstaller
packaging\build_windows.bat
:: → dist\AI-PDF.exe
```
Run: Double-click `AI-PDF.exe`. No installation needed — it's a single
portable executable. Copy it to any folder (Desktop, Program Files, USB).

## GPU acceleration

The packaged app ships with a **CPU-only** `llama-cpp-python` build for
universality. On first run, if an NVIDIA GPU is detected (Linux/Windows),
the app downloads a CUDA-built `libllama` shared library (~15 MB) into
the app's data directory and prompts the user to restart. After restart,
AI inference uses the GPU automatically.

## Data directories

The app stores all user data in OS-specific locations:
| Platform | Path |
|---|---|
| Linux | `~/.local/share/ai-pdf/` |
| Windows | `%APPDATA%\ai-pdf\` |

Subdirectories:
- `notes/<pdf-name>/` — per-PDF notes, highlights, captures, annotations
- `models/` — HuggingFace model cache (GGUF + mmproj)
- `voices/` — Piper TTS voice files
- `native/` — CUDA-built libllama (auto-downloaded)
- `ai.log` — rotating log file

## App icon

Source: `packaging/icons/ai-pdf.svg`
- `ai-pdf.png` (256×256) — used by AppImage
- `ai-pdf.ico` (multi-res) — embedded in Windows exe

## How the build works

1. **PyInstaller** bundles the Python app + all deps into either:
   - `dist/AI-PDF/` (onedir — for AppImage)
   - `dist/AI-PDF.exe` (onefile — for Windows)
2. **Qt6 trimming**: The spec filters out ~400 MB of unused Qt6 modules
   (WebEngine, QML, 3D, Multimedia, SQL, etc.) by removing them from
   the binary list before packaging.
3. **AppImage assembly** (Linux only):
   - The onedir bundle is placed into `AppDir/usr/bin/`
   - `AppRun` script + `.desktop` file + icon are placed at the AppDir root
   - `appimagetool` packs AppDir into a single `.AppImage` file
4. **appimagetool** is auto-downloaded to `~/.local/bin/` if not present.

## Bundle sizes (approximate)

| Output | Size |
|---|---|
| Linux AppImage | ~200 MB |
| Windows EXE | ~200 MB |

## CUDA library hosting

The CUDA `libllama` binaries are hosted as HuggingFace assets in the
`ai-pdf/native-libs` repo. To build and upload:

```sh
# Linux CUDA build
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall llama-cpp-python
python -c "import llama_cpp, pathlib; p=pathlib.Path(llama_cpp.__file__).parent; print(p)"
# Find libllama.so → rename to libllama-cuda12-linux-x64.so → upload to HF

# Windows CUDA build (on a Windows machine with CUDA Toolkit)
set CMAKE_ARGS=-DGGML_CUDA=on
pip install --force-reinstall llama-cpp-python
# Find llama.dll → rename to llama-cuda-win-x64.dll → upload to HF
```
