# AGENTS.md

## What this is
Single-binary Python app: a native GUI PDF reader with integrated Markdown notes, a built-in local AI layer (multimodal Gemma 4), and accessibility for blind users (TTS narration + image descriptions). Source lives under `src/pyxis/` (an installable package); entry point is `pyxis.main:main`, runnable via the `pyxis` console script or `python -m pyxis` after `pip install -e .`.

## Build & run
- Install (editable, registers the `pyxis` console script): `pip install -e ".[dev]"`
- GPU build (NVIDIA): `CMAKE_ARGS="-DGGML_CUDA=on" pip install --upgrade --force-reinstall llama-cpp-python`
- Run: `pyxis` (welcome screen) or `pyxis <file.pdf>` (auto-opens a file). Equivalent: `python -m pyxis`.
- No tests, no formatter/lint config. CI (`.github/workflows/build.yml`) only builds the Linux AppImage + Windows EXE on tag push. Match the existing zero-config style.

## Architecture
- `src/pyxis/main.py` (~700 lines) — PyQt6 application. `MainWindow` with toolbar, left sidebar (bookmarks/info), right notes panel, scrollable page view, keyboard handling, search, highlights, capture, AI menu, and the accessibility toggle.
- `src/pyxis/pdf_engine.py` (~120 lines) — `PdfEngine` wraps PyMuPDF; handles loading, rendering to `QImage`, text extraction with char bounds, search, and bookmarks.
- `src/pyxis/page_view.py` (~190 lines) — `PageView` custom `QLabel` subclass. Displays a page, renders text-selection/highlight/image-focus overlays, and emits right-click / capture / describe-image signals.
- `src/pyxis/storage.py` (~120 lines) — `PdfStorage` manages per-PDF folders at `notes/<pdf-name>/` with `notes.md`, `highlights/`, `captures/`, and `annotations.json` (includes `image_descriptions` cache).
- `src/pyxis/notes_panel.py` — `NotesPanel` Obsidian-style live-preview Markdown editor. `_block_raw` (a list of markdown block strings) is the source of truth; the `QTextDocument` is a rendered view. The block under the cursor shows raw markdown (markers are real, editable chars there); every other block is rendered via `QTextDocumentFragment.fromHtml(render_markdown_html(...))` with markers absent and inline images as `QPixmap` resources keyed by `file://` URI. Debounced+atomic autosave of `notes.md` (B6), pasted U+FFFC stripped (B2), TTS reads `get_plain_text()` (B4). Known limitation: multi-block cross-block selection deletes aren't reconciled (content may reappear on re-render); no corruption.
- `src/pyxis/ai_layer.py` (~480 lines) — `AILayer` detects RAM/accel, picks a Gemma 4 model from `TIERS`, resolves GGUF quants + mmproj sidecar via Hugging Face, loads `llama-cpp-python` with `Gemma4ChatHandler` for vision, and runs 6 text commands + `describe_image`.
- `src/pyxis/ai_workers.py` (~85 lines) — `LoadWorker`, `IndexWorker`, `InferWorker` `QThread`s so the UI never blocks; tokens stream as `pyqtSignal`.
- `src/pyxis/rag.py` (~135 lines) — `RagIndex` BM25 + fuzzy-blend retrieval over paragraphs/tables/images with budget-aware context assembly.
- `src/pyxis/speech.py` (~150 lines) — `PiperEngine` (neural TTS, primary) / `Pyttsx3Engine` (fallback) + `SpeechQueue` QThread for sentence-grained playback.
- `src/pyxis/narrator.py` (~120 lines) — `NarratorWorker` walks RAG chunks per page: text → TTS, images → vision model → notes + TTS.
- `src/pyxis/__main__.py` — thin module entry for `python -m pyxis`; uses an absolute self-import (`from pyxis.main import main`) so the package initializes and relative imports inside `main.py` resolve.
- Rendered page bitmaps are cached in `PdfEngine` with an LRU eviction policy (`MAX_CACHE = 50`).

## Conventions specific to this repo
- Package layout: source lives under `src/pyxis/`; install with `pip install -e ".[dev]"`, run via `pyxis` or `python -m pyxis`. **Intra-package imports are relative** (`from .pdf_engine import …`); the only absolute self-import is `from pyxis.main import main` in `__main__.py`.
- Dark theme via `QPalette` in `src/pyxis/main.py`.
- Window starts at 1600×900 but is resizable; fit-to-width zoom adapts to viewport width.
- Keyboard shortcuts are centralized in `MainWindow.keyPressEvent`.
- Default zoom state: `fit_to_width = True`, `zoom_index = 5` (ZOOM_LEVELS index for 1.0). `ZOOM_LEVELS` is at `src/pyxis/pdf_engine.py:4`.
- Each opened PDF gets its own folder at `notes/<pdf-name>/`.
- Highlights and captures are saved as PNGs and appended to the PDF's `notes.md` in Markdown format.
- AI model is per-machine (one load, reused across PDFs). Gemma 4 is the auto-pick family (multimodal); Qwen2.5 is retained as a text-only secondary option in the model menu. KV-cache uses `type_k=q8_0` (tightened to `q4_0` below 12 GB).
- Gemma 4 thinking mode (`<|think|>` token) is disabled by default for narration/summarization (fast) and `describe_image` (24s vs 132s with thinking).

## Accessibility (blind users)
- Toggle via 🎧 toolbar button or `Ctrl+Shift+A`. When on:
  - Piper TTS engine downloads a ~65 MB voice file on first run (`~/.local/share/pyxis/voices/`).
  - `NarratorWorker` reads pages aloud: paragraph/table text → TTS; image chunks → Gemma 4 vision model → caption appended to notes + spoken.
  - Image descriptions are cached in `annotations.json["image_descriptions"]` so re-opening a PDF skips re-running the model.
  - A secondary accessibility toolbar appears below the main one with **Speed** (0.5×–2.0×) and **Volume** (0–100%) sliders plus Pause/Stop/Continue/Help buttons. Slider changes are pushed live to the TTS engine (`PiperEngine` uses Piper's `SynthesisConfig(length_scale, volume)`; falls back to int16 scaling + no-op rate when `SynthesisConfig` isn't importable).
  - Pause/resume is **sentence-grained**: `SpeechQueue.pause()` cancels the in-flight chunk, stashes it, and `resume()` replays that sentence from the top. Resume position is persisted per-PDF in `annotations.json["narration_position"]` (`{"page", "chunk", "timestamp"}`) on every `chunk_progress` signal and on page completion, so `C` ("Continue reading") works across sessions.
- Keyboard shortcuts (only active when a11y is on):
  - `Space`/`P` — pause/resume narration
  - `R` — read current page from start
  - `C` — continue reading from saved position (cross-session resume)
  - `S` — stop narration and clear queue
  - `I` — describe next image on current page
  - `N` — read notes panel aloud
  - `?` — open the Accessibility Help window and read it aloud (the keybind list lives in `A11Y_KEYBINDS` at the top of `src/pyxis/main.py`)
  - `Esc` — stop narration (or cancel AI, or clear search — context-dependent)
  - `Alt+Left/Right` — navigate pages (stops narration first)
- Right-clicking an image region in `PageView` triggers description immediately.

## Notes PDF export
- The `NotesPanel` "PDF" button exports `notes.md` to a PDF via `QTextDocument.print(QPrinter)`.
- Image references (`![alt](rel/path.png)`) are resolved against the PDF's `notes/<pdf-name>/` folder and **pre-registered as `QTextDocument` image resources** before `setHtml`, so the bitmaps embed into the exported PDF instead of leaving a broken `file://` path placeholder.

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
- Entry point: `src/pyxis/main.py` (module entry: `src/pyxis/__main__.py`)
- Engine: `src/pyxis/pdf_engine.py`
- Page widget: `src/pyxis/page_view.py`
- Storage: `src/pyxis/storage.py`
- Notes panel: `src/pyxis/notes_panel.py`
- AI layer: `src/pyxis/ai_layer.py`, `src/pyxis/ai_workers.py`
- RAG: `src/pyxis/rag.py`
- TTS: `src/pyxis/speech.py`
- Narrator: `src/pyxis/narrator.py`
