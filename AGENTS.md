# AGENTS.md

## What this is
Single-binary Python app: a native GUI PDF reader with integrated Markdown notes, a built-in local AI layer (multimodal Gemma 4), and accessibility for blind users (TTS narration + image descriptions). Entry point is `main.py`.

## Build & run
- Install: `pip install -r requirements.txt`
- GPU build (NVIDIA): `CMAKE_ARGS="-DGGML_CUDA=on" pip install --upgrade --force-reinstall llama-cpp-python`
- Run: `python main.py` (opens welcome screen) or `python main.py <file.pdf>` (auto-opens a file)
- No tests, no formatter/lint config, no CI. Match the existing zero-config style.

## Architecture
- `main.py` (~700 lines) — PyQt6 application. `MainWindow` with toolbar, left sidebar (bookmarks/info), right notes panel, scrollable page view, keyboard handling, search, highlights, capture, AI menu, and the accessibility toggle.
- `pdf_engine.py` (~120 lines) — `PdfEngine` wraps PyMuPDF; handles loading, rendering to `QImage`, text extraction with char bounds, search, and bookmarks.
- `page_view.py` (~190 lines) — `PageView` custom `QLabel` subclass. Displays a page, renders text-selection/highlight/image-focus overlays, and emits right-click / capture / describe-image signals.
- `storage.py` (~120 lines) — `PdfStorage` manages per-PDF folders at `notes/<pdf-name>/` with `notes.md`, `highlights/`, `captures/`, and `annotations.json` (includes `image_descriptions` cache).
- `notes_panel.py` (~430 lines) — `NotesPanel` WYSIWYG Markdown editor that hides syntax markers, renders inline images, auto-saves `notes.md`, plus streaming helpers for AI output.
- `ai_layer.py` (~480 lines) — `AILayer` detects RAM/accel, picks a Gemma 4 model from `TIERS`, resolves GGUF quants + mmproj sidecar via Hugging Face, loads `llama-cpp-python` with `Gemma4ChatHandler` for vision, and runs 6 text commands + `describe_image`.
- `ai_workers.py` (~85 lines) — `LoadWorker`, `IndexWorker`, `InferWorker` `QThread`s so the UI never blocks; tokens stream as `pyqtSignal`.
- `rag.py` (~135 lines) — `RagIndex` BM25 + fuzzy-blend retrieval over paragraphs/tables/images with budget-aware context assembly.
- `speech.py` (~150 lines) — `PiperEngine` (neural TTS, primary) / `Pyttsx3Engine` (fallback) + `SpeechQueue` QThread for sentence-grained playback.
- `narrator.py` (~120 lines) — `NarratorWorker` walks RAG chunks per page: text → TTS, images → vision model → notes + TTS.
- Rendered page bitmaps are cached in `PdfEngine` with an LRU eviction policy (`MAX_CACHE = 50`).

## Conventions specific to this repo
- Dark theme via `QPalette` in `main.py`.
- Window starts at 1600×900 but is resizable; fit-to-width zoom adapts to viewport width.
- Keyboard shortcuts are centralized in `MainWindow.keyPressEvent`.
- Default zoom state: `fit_to_width = True`, `zoom_index = 5` (ZOOM_LEVELS index for 1.0). `ZOOM_LEVELS` is at `pdf_engine.py:4`.
- Each opened PDF gets its own folder at `notes/<pdf-name>/`.
- Highlights and captures are saved as PNGs and appended to the PDF's `notes.md` in Markdown format.
- AI model is per-machine (one load, reused across PDFs). Gemma 4 is the auto-pick family (multimodal); Qwen2.5 is retained as a text-only secondary option in the model menu. KV-cache uses `type_k=q8_0` (tightened to `q4_0` below 12 GB).
- Gemma 4 thinking mode (`<|think|>` token) is disabled by default for narration/summarization (fast) and `describe_image` (24s vs 132s with thinking).

## Accessibility (blind users)
- Toggle via 🎧 toolbar button or `Ctrl+Shift+A`. When on:
  - Piper TTS engine downloads a ~65 MB voice file on first run (`~/.local/share/pyxis/voices/`).
  - `NarratorWorker` reads pages aloud: paragraph/table text → TTS; image chunks → Gemma 4 vision model → caption appended to notes + spoken.
  - Image descriptions are cached in `annotations.json["image_descriptions"]` so re-opening a PDF skips re-running the model.
- Keyboard shortcuts (only active when a11y is on):
  - `Space`/`P` — pause/resume narration
  - `R` — read current page from start
  - `S` — stop narration and clear queue
  - `I` — describe next image on current page
  - `N` — read notes panel aloud
  - `Esc` — stop narration (or cancel AI, or clear search — context-dependent)
  - `Alt+Left/Right` — navigate pages (stops narration first)
- Right-clicking an image region in `PageView` triggers description immediately.

## Model tiers
Gemma 4 (auto-pick, multimodal — text + image + audio on E2B/E4B):
| min_ram | Model | Q4 size | Repo |
|---|---|---|---|
| 16 GB | Gemma 4 12B-it | 7.1 GB | `unsloth/gemma-4-12b-it-GGUF` |
| 14 GB | Gemma 4 12B-it (IQ4_XS) | 6.4 GB | same |
| 12 GB | Gemma 4 E4B-it | 5.0 GB | `unsloth/gemma-4-E4B-it-GGUF` |
| 10 GB | Gemma 4 E4B-it (IQ4_XS) | 4.7 GB | same |
| 8 GB | Gemma 4 E2B-it | 3.1 GB | `unsloth/gemma-4-E2B-it-GGUF` |

Qwen2.5 (manual selection, text-only fallback):
14B / 7B / 3B Instruct at `Qwen/Qwen2.5-*-Instruct-GGUF`.

All Gemma 4 repos also ship `mmproj-F16.gguf` (vision projector sidecar) — `load_model` downloads it alongside the main GGUF and attaches a `Gemma4ChatHandler`.

## Files worth knowing
- Entry point: `main.py`
- Engine: `pdf_engine.py`
- Page widget: `page_view.py`
- Storage: `storage.py`
- Notes panel: `notes_panel.py`
- AI layer: `ai_layer.py`, `ai_workers.py`
- RAG: `rag.py`
- TTS: `speech.py`
- Narrator: `narrator.py`
