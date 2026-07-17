# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI-PDF.

Build:  pyinstaller packaging/ai-pdf.spec
Output: dist/AI-PDF/  (onedir mode — faster startup than onefile, and
        llama-cpp-python's native libs don't like being re-extracted on
        every launch).

The spec declares every dynamic/hidden import that PyInstaller's static
analysis can't follow (chat handlers, fallback TTS, NVML, etc.) and
collects all native binaries from the heavy deps.
"""

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Resolve paths relative to the project root (spec file is in packaging/)
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# ── Collect native binaries + data from heavy deps ────────────────────────
pyqt6_bins, pyqt6_datas, pyqt6_hidden = collect_all("PyQt6")
fitz_bins, fitz_datas, fitz_hidden = collect_all("fitz")
llama_bins, llama_datas, llama_hidden = collect_all("llama_cpp")
piper_bins, piper_datas, piper_hidden = collect_all("piper")
onnx_bins, onnx_datas, onnx_hidden = collect_all("onnxruntime")
rf_bins, rf_datas, rf_hidden = collect_all("rapidfuzz")

# Filter out Qt6 modules we don't use (WebEngine, 3D, Multimedia, etc.)
_QT_SKIP = ("WebEngine", "WebSockets", "WebView", "Qml", "Quick", "3D",
            "Multimedia", "Designer", "Help", "Nfc", "Positioning",
            "RemoteObjects", "Sensors", "SerialPort", "SpatialAudio",
            "Sql", "Test", "Bluetooth", "Charts", "DataVisualization",
            "Pdf", "OpenGL", "Scxml", "Svg", "UiTools", "AxContainer",
            "Network")
def _filter_bins(bins):
    return [b for b in bins if not any(s in os.path.basename(b[0]) for s in _QT_SKIP)]
def _filter_datas(datas):
    return [d for d in datas if not any(s in os.path.basename(d[0]) for s in _QT_SKIP)]
pyqt6_bins = _filter_bins(pyqt6_bins)
pyqt6_datas = _filter_datas(pyqt6_datas)

# sounddevice is a pure-Python package (no collect_all needed)
sd_hidden = collect_submodules("sounddevice")

hiddenimports = [
    # Dynamic / try-except imports that static analysis misses
    "llama_cpp.llama_chat_format",
    "llama_cpp.llama_chat_format.Gemma4ChatHandler",
    "llama_cpp.llama_chat_format.MTMDChatHandler",
    "llama_cpp.llama_chat_format.Llava15ChatHandler",
    "psutil",
    "pynvml",
    "pyttsx3",
    "numpy",
    "sounddevice",
    "huggingface_hub",
    "huggingface_hub.hf_api",
    "markdown_it",
    "mdit_py_plugins",
    "mdit_py_plugins.dollarmath",
    "mdit_py_plugins.tasklists",
    "linkify_it",
    "rank_bm25",
    "rapidfuzz",
    "rapidfuzz.fuzz",
] + pyqt6_hidden + fitz_hidden + llama_hidden + piper_hidden + sd_hidden + onnx_hidden + rf_hidden

# Trim unnecessary transitive deps to shrink the bundle by ~500 MB
excludes = [
    "matplotlib", "scipy", "pandas", "torch", "transformers",
    "IPython", "pytest", "tkinter", "notebook", "jupyter",
    "PyQt5", "PySide6",
    # Qt6 modules we don't use (WebEngine alone is ~200 MB)
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
    "PyQt6.QtUiTools", "PyQt6.QtAxContainer",
    "PyQt6.QtNetwork",
    "hf_xet",
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=(
        pyqt6_bins + fitz_bins + llama_bins + piper_bins
        + onnx_bins + rf_bins
    ),
    datas=(
        pyqt6_datas + fitz_datas + llama_datas + piper_datas
        + onnx_datas + rf_datas
    ),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-PDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(os.path.join(SPEC_DIR, "icons", "ai-pdf.ico") if sys.platform == "win32"
          else os.path.join(SPEC_DIR, "icons", "ai-pdf.icns") if sys.platform == "darwin"
          else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI-PDF",
)

# ── Post-build cleanup: remove unused Qt6 shared libs ─────────────────────
# PyInstaller's collect_all pulls in every Qt6 module; excludes only prevent
# Python imports, not .so files. We strip the big ones we know we don't use.
import shutil as _sh
_QT_LIB_SKIP = (
    "libQt6WebEngine", "libQt6WebSockets", "libQt6WebView",
    "libQt6Qml", "libQt6Quick", "libQt6Quick3D", "libQt63D",
    "libQt6Multimedia", "libQt6Pdf", "libQt6Sql", "libQt6Scxml",
    "libQt6Svg", "libQt6Test", "libQt6Network", "libQt6ShaderTools",
    "libQt6OpenGL",
    "libavcodec", "libavformat", "libavutil", "libswscale", "libswresample",
    "libx265", "libx264", "libaom", "libvpx",
    # NOTE: ICU libs (libicudata, libicui18n, libicuuc) are REQUIRED by Qt6Core
    # — do NOT trim them.
)
_dist = os.path.join(PROJECT_ROOT, "dist", "AI-PDF", "_internal")
for _f in os.listdir(_dist):
    if any(_f.startswith(s) for s in _QT_LIB_SKIP):
        _p = os.path.join(_dist, _f)
        _os = os.path.getsize(_p)
        os.remove(_p)
        print(f"  Trimmed {_f} ({_os // 1048576} MB)")
# Also clean Qt6 subdirectory libs + plugins we don't use
_qt_lib_dir = os.path.join(_dist, "PyQt6", "Qt6", "lib")
if os.path.isdir(_qt_lib_dir):
    for _f in os.listdir(_qt_lib_dir):
        if any(_f.startswith(s) for s in _QT_LIB_SKIP):
            _p = os.path.join(_qt_lib_dir, _f)
            _os = os.path.getsize(_p)
            os.remove(_p)
            print(f"  Trimmed Qt6/lib/{_f} ({_os // 1048576} MB)")
# Remove unused Qt6 plugins
_qt_plugins_dir = os.path.join(_dist, "PyQt6", "Qt6", "plugins")
_qt_plugin_skip = ("sceneparsers", "assetimporters", "qmlls", "qmllint",
                   "sqldrivers", "renderers", "renderplugins",
                   "scxmldatamodel", "multimedia", "tls", "webview",
                   "texttospeech", "geometryloaders", "help", "position",
                   "sensors", "wayland-decoration-client",
                   "wayland-graphics-integration-client",
                   "wayland-shell-integration")
if os.path.isdir(_qt_plugins_dir):
    for _d in os.listdir(_qt_plugins_dir):
        if _d in _qt_plugin_skip:
            _p = os.path.join(_qt_plugins_dir, _d)
            _sh.rmtree(_p)
            print(f"  Trimmed plugins/{_d}/")
# Remove QML directory entirely (we don't use QML)
_qml_dir = os.path.join(_dist, "PyQt6", "Qt6", "qml")
if os.path.isdir(_qml_dir):
    _sh.rmtree(_qml_dir)
    print("  Trimmed Qt6/qml/ (entire directory)")
# Remove translations (saves ~11 MB)
_tr_dir = os.path.join(_dist, "PyQt6", "Qt6", "translations")
if os.path.isdir(_tr_dir):
    _sh.rmtree(_tr_dir)
    print("  Trimmed Qt6/translations/")
# Remove qsci (QScintilla, not used)
_qsci_dir = os.path.join(_dist, "PyQt6", "Qt6", "qsci")
if os.path.isdir(_qsci_dir):
    _sh.rmtree(_qsci_dir)
    print("  Trimmed Qt6/qsci/")
