# AGENTS.md

## What this is
Single-binary Python app: a native GUI PDF reader with integrated Markdown notes. Entry point is `main.py`.

## Build & run
- Install: `pip install -r requirements.txt`
- Run: `python main.py` (opens welcome screen) or `python main.py <file.pdf>` (auto-opens a file)
- No tests, no formatter/lint config, no CI. Match the existing zero-config style.

## Architecture
- `main.py` (~420 lines) — PyQt6 application. `MainWindow` with toolbar, left sidebar (bookmarks/info), right notes panel, scrollable page view, keyboard handling, search, highlights, and capture.
- `pdf_engine.py` (~120 lines) — `PdfEngine` wraps PyMuPDF; handles loading, rendering to `QImage`, text extraction with char bounds, search, and bookmarks.
- `page_view.py` (~160 lines) — `PageView` custom `QLabel` subclass. Displays a page, renders text-selection and highlight overlays, and emits right-click / capture signals.
- `storage.py` (~95 lines) — `PdfStorage` manages per-PDF folders at `notes/<pdf-name>/` with `notes.md`, `highlights/`, `captures/`, and `annotations.json`.
- `notes_panel.py` (~40 lines) — `NotesPanel` is a plain-text Markdown editor that auto-saves `notes.md`.
- Rendered page bitmaps are cached in `PdfEngine` with an LRU eviction policy (`MAX_CACHE = 50`).

## Conventions specific to this repo
- Dark theme via `QPalette` in `main.py`.
- Window starts at 1600×900 but is resizable; fit-to-width zoom adapts to viewport width.
- Keyboard shortcuts are centralized in `MainWindow.keyPressEvent`.
- Default zoom state: `fit_to_width = True`, `zoom_index = 5` (ZOOM_LEVELS index for 1.0). `ZOOM_LEVELS` is at `pdf_engine.py:4`.
- Each opened PDF gets its own folder at `notes/<pdf-name>/`.
- Highlights and captures are saved as PNGs and appended to the PDF's `notes.md` in Markdown format.

## Files worth knowing
- Entry point: `main.py`
- Engine: `pdf_engine.py`
- Page widget: `page_view.py`
- Storage: `storage.py`
- Notes panel: `notes_panel.py`
