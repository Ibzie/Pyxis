# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI-PDF.

Supports two modes via the AIPDF_ONEFILE env var:
  - AIPDF_ONEFILE=1  → single .exe (Windows portable)
  - default          → onedir (for Linux AppImage)

Build:
  Linux:  ./packaging/build_linux.sh        (onedir → AppImage)
  Windows: packaging\\build_windows.bat      (onefile → AI-PDF.exe)
"""

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)
ONEFILE = os.environ.get("AIPDF_ONEFILE", "") == "1"

# ── Collect native binaries + data from heavy deps ────────────────────────
pyqt6_bins, pyqt6_datas, pyqt6_hidden = collect_all("PyQt6")
fitz_bins, fitz_datas, fitz_hidden = collect_all("fitz")
llama_bins, llama_datas, llama_hidden = collect_all("llama_cpp")
piper_bins, piper_datas, piper_hidden = collect_all("piper")
onnx_bins, onnx_datas, onnx_hidden = collect_all("onnxruntime")
rf_bins, rf_datas, rf_hidden = collect_all("rapidfuzz")
sd_hidden = collect_submodules("sounddevice")

# ── Filter out unused Qt6 modules (saves ~400 MB) ─────────────────────────
# PyInstaller's collect_all grabs every Qt6 .so; excludes only prevent Python
# imports, not binary files. We filter the binary/data lists directly so the
# trimming works for both onedir and onefile builds.
_QT_BIN_SKIP = (
    "libQt6WebEngine", "libQt6WebSockets", "libQt6WebView",
    "libQt6Qml", "libQt6Quick", "libQt6Quick3D", "libQt63D",
    "libQt6Multimedia", "libQt6Pdf", "libQt6Sql", "libQt6Scxml",
    "libQt6Svg", "libQt6Test", "libQt6Network", "libQt6ShaderTools",
    "libQt6OpenGL",
    "libavcodec", "libavformat", "libavutil", "libswscale", "libswresample",
    "libx265", "libx264", "libaom", "libvpx",
    # ICU libs (libicudata, libicui18n, libicuuc) are REQUIRED by Qt6Core.
)
_QT_DATA_SKIP_DIRS = (
    "qml", "translations", "qsci",
    "plugins/sceneparsers", "plugins/assetimporters", "plugins/qmlls",
    "plugins/qmllint", "plugins/sqldrivers", "plugins/renderers",
    "plugins/renderplugins", "plugins/scxmldatamodel", "plugins/multimedia",
    "plugins/tls", "plugins/webview", "plugins/texttospeech",
    "plugins/geometryloaders", "plugins/help", "plugins/position",
    "plugins/sensors", "plugins/wayland-decoration-client",
    "plugins/wayland-graphics-integration-client",
    "plugins/wayland-shell-integration",
)

def _skip_bin(name):
    base = os.path.basename(name)
    return any(base.startswith(s) for s in _QT_BIN_SKIP)

def _skip_data(name):
    # name is like "PyQt6/Qt6/qml/..." — check path segments
    norm = name.replace("\\", "/")
    return any(s in norm for s in _QT_DATA_SKIP_DIRS)

all_bins = (pyqt6_bins + fitz_bins + llama_bins + piper_bins
            + onnx_bins + rf_bins)
all_datas = (pyqt6_datas + fitz_datas + llama_datas + piper_datas
             + onnx_datas + rf_datas)

# Filter and report
_orig_bin = len(all_bins)
all_bins = [tuple(b) for b in all_bins if not _skip_bin(b[0])]
_orig_data = len(all_datas)
all_datas = [tuple(d) for d in all_datas if not _skip_data(d[0])]
print(f"  Filtered {_orig_bin - len(all_bins)} binaries, "
      f"{_orig_data - len(all_datas)} data entries (Qt trim)")

hiddenimports = [
    "llama_cpp.llama_chat_format",
    "llama_cpp.llama_chat_format.Gemma4ChatHandler",
    "llama_cpp.llama_chat_format.MTMDChatHandler",
    "llama_cpp.llama_chat_format.Llava15ChatHandler",
    "psutil", "pynvml", "pyttsx3", "numpy", "sounddevice",
    "huggingface_hub", "huggingface_hub.hf_api",
    "markdown_it", "mdit_py_plugins", "mdit_py_plugins.dollarmath",
    "mdit_py_plugins.tasklists", "linkify_it",
    "rank_bm25", "rapidfuzz", "rapidfuzz.fuzz",
] + pyqt6_hidden + fitz_hidden + llama_hidden + piper_hidden + sd_hidden + onnx_hidden + rf_hidden

excludes = [
    "matplotlib", "scipy", "pandas", "torch", "transformers",
    "IPython", "pytest", "tkinter", "notebook", "jupyter",
    "PyQt5", "PySide6",
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuick3D", "PyQt6.QtQuickWidgets",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
    "PyQt6.QtWebSockets", "PyQt6.QtWebView", "PyQt6.QtWebViewQuick",
    "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets", "PyQt6.QtNfc", "PyQt6.QtPositioning",
    "PyQt6.QtRemoteObjects", "PyQt6.QtSensors", "PyQt6.QtSerialPort",
    "PyQt6.QtSpatialAudio", "PyQt6.QtSql", "PyQt6.QtTest",
    "PyQt6.QtBluetooth", "PyQt6.QtCharts", "PyQt6.QtDataVisualization",
    "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic", "PyQt6.Qt3DExtras", "PyQt6.Qt3DAnimation",
    "PyQt6.QtPdf", "PyQt6.QtPdfWidgets",
    "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtScxml", "PyQt6.QtSvg", "PyQt6.QtSvgWidgets",
    "PyQt6.QtUiTools", "PyQt6.QtAxContainer", "PyQt6.QtNetwork",
    "hf_xet",
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=all_bins,
    datas=all_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_icon = (os.path.join(SPEC_DIR, "icons", "ai-pdf.ico") if sys.platform == "win32"
         else os.path.join(SPEC_DIR, "icons", "ai-pdf.icns") if sys.platform == "darwin"
         else None)

if ONEFILE:
    # ── Single-file mode (Windows portable exe) ───────────────────────────
    # Everything packed into one .exe. Slower startup (~5s extraction to temp
    # on first run) but simplest distribution — no install needed.
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas,
        name="AI-PDF",
        debug=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=_icon,
    )
else:
    # ── Onedir mode (Linux → AppImage) ────────────────────────────────────
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="AI-PDF",
        debug=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=_icon,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="AI-PDF",
    )
