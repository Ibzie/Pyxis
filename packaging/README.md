# Pyxis Packaging

Build scripts for Linux (AppImage) and Windows (portable EXE).

## Quick start

### Linux — AppImage
```sh
# From the project root:
pip install -r requirements.txt
pip install pyinstaller
./packaging/build_linux.sh
# → dist/Pyxis-<version>-x86_64.AppImage  (version from pyproject.toml;
#    override with PYXIS_VERSION=… — CI passes the pushed git tag)
```
Run: `chmod +x dist/Pyxis-*.AppImage && ./dist/Pyxis-*.AppImage`

Install (optional): `mv dist/Pyxis-*.AppImage ~/.local/bin/pyxis`

The AppImage is a single self-contained executable — no installation,
no root permissions, no dependencies. It mounts via FUSE and runs.

### Windows — Portable EXE
```bat
pip install -r requirements.txt
pip install pyinstaller
set PYXIS_VERSION=1.2.3
packaging\build_windows.bat
:: → dist\Pyxis-1.2.3-x64.exe  (without PYXIS_VERSION: dist\Pyxis.exe)
```
Run: Double-click the exe. No installation needed — it's a single
portable executable. Copy it to any folder (Desktop, Program Files, USB).

### CI release naming
Pushing a `v*` tag triggers `.github/workflows/build.yml`, which names both
artifacts after the tag: `Pyxis-<tag>-x86_64.AppImage` and
`Pyxis-<tag>-x64.exe` (e.g. tag `v1.2.3` → `Pyxis-1.2.3-…`). Local builds
fall back to the version declared in `pyproject.toml`.

### Audio in the frozen build (PortAudio)

`sounddevice` dlopens PortAudio by bare soname at runtime, and the PyPI
Linux wheel does **not** bundle it — a frozen build would silently depend
on the target machine having `libportaudio` installed (not present on a
clean Arch/CachyOS install → no audio at all). Two things make the
AppImage self-sufficient:

1. `packaging/pyxis.spec` resolves the build host's `libportaudio.so.2`
   and ships it (PyInstaller follows its ALSA dependency chain).
2. `packaging/AppRun` exports `LD_LIBRARY_PATH` pointing at the bundle's
   `_internal/` — a dlopen-by-soname search does not see the executable's
   rpath, so without this the bundled copy is never found.

Verify any build end-to-end with:
`PYXIS_SELFTEST=1 ./Pyxis-<version>-x86_64.AppImage <file.pdf>`
(plays ~30 s of real narration, prints a trace, exits 0 on pass).

## GPU acceleration

The packaged app ships with a **CPU-only** `llama-cpp-python` build for
universality. To ship GPU builds, install a CUDA-built wheel in the build
environment before packaging — PyInstaller bundles whatever is installed:

```sh
CMAKE_ARGS="-DGGML_CUDA=on" pip install --force-reinstall llama-cpp-python
```

## Data directories

The app stores all user data in OS-specific locations:
| Platform | Path |
|---|---|
| Linux | `~/.local/share/pyxis/` |
| Windows | `%APPDATA%\pyxis\` |

Subdirectories:
- `notes/<pdf-name>/` — per-PDF notes, highlights, captures, annotations
- `models/` — HuggingFace model cache (GGUF + mmproj)
- `voices/` — Piper TTS voice files
- `ai.log` — rotating log file

## App icon

Source: `packaging/icons/pyxis.svg`
- `pyxis.png` (256×256) — used by AppImage
- `pyxis.ico` (multi-res) — embedded in Windows exe

## How the build works

1. **PyInstaller** bundles the Python app + all deps into either:
   - `dist/Pyxis/` (onedir — for AppImage)
   - `dist/Pyxis.exe` (onefile — for Windows)
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
