# AGENTS.md

## What this is
Single-binary Python app: a native GUI PDF reader. Entry point is `main.py`.

## Build & run
- Install: `pip install -r requirements.txt`
- Run: `python main.py` (opens welcome screen) or `python main.py <file.pdf>` (auto-opens a file)
- No tests, no formatter/lint config, no CI. Match the existing zero-config style.

## Architecture
- `main.py` (~400 lines) — entire PyQt6 application. `MainWindow` with toolbar, sidebar, scrollable page view, keyboard handling, search, highlights, and capture.
- `pdf_engine.py` (~110 lines) — `PdfEngine` wraps PyMuPDF; handles loading, rendering to `QImage`, text extraction with char bounds, search, and bookmarks.
- `page_view.py` (~160 lines) — `PageView` custom `QLabel` subclass. Displays a page, renders text-selection and highlight overlays, and emits right-click / capture signals.
- Rendered page bitmaps are cached in `PdfEngine` with an LRU eviction policy (`MAX_CACHE = 50`).

## Conventions specific to this repo
- Dark theme via `QPalette` in `main.py`.
- Window starts at 1400×900 but is resizable; fit-to-width zoom adapts to viewport width.
- Keyboard shortcuts are centralized in `MainWindow.keyPressEvent`.
- Default zoom state: `fit_to_width = True`, `zoom_index = 5` (ZOOM_LEVELS index for 1.0). `ZOOM_LEVELS` is at `pdf_engine.py:4`.
- Captures and annotation JSON are written to a `captures/` directory next to the app.

## Files worth knowing
- Entry point: `main.py`
- Engine: `pdf_engine.py`
- Page widget: `page_view.py`
