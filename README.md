# Pyxis

A local-first PDF reader with AI notes, vision, and accessibility for blind users. 100% offline — your data never leaves your machine.

## Features

- **Native PDF rendering** via PyMuPDF (MuPDF) with LRU render cache
- **WYSIWYG Markdown notes** — syntax markers hide visually, inline images render, auto-saves per PDF
- **Multimodal AI (Gemma 4)** — summarize notes/pages, Q&A with RAG + page citations, extract to-dos, draft follow-ups, suggest tags. Streams output live into notes.
- **Accessibility mode** 🎧 — Piper neural TTS reads pages aloud; vision model describes images for blind users; descriptions cached for re-opening
- **RAG retrieval** — BM25 + fuzzy blend over paragraphs/tables/images with budget-aware context assembly
- **Highlights & captures** — saved as PNGs, embedded into notes
- **Cross-platform** — Linux (AppImage), Windows (portable EXE)
- **Dark theme** by default
- **No cloud, no API keys, no telemetry**

> The AI layer needs ≥ 8 GB RAM. On first use it downloads an open-weights Gemma 4 GGUF model (sized to your machine) + a ~65 MB Piper voice file. If you have an NVIDIA GPU, it auto-downloads a CUDA build for faster inference.

## Download

Pre-built binaries are on the [GitHub Releases](../../releases) page:

- **Linux**: `Pyxis-x86_64.AppImage` — single file, no install. `chmod +x && ./Pyxis-*.AppImage`
- **Windows**: `Pyxis.exe` — single portable executable. Double-click to run.

## Build from source

Requires Python 3.10+.

```bash
git clone https://github.com/Ibzie/Pyxis.git
cd Pyxis
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For GPU acceleration (NVIDIA) build `llama-cpp-python` against CUDA:

```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install --upgrade --force-reinstall llama-cpp-python
```

On Apple Silicon, Metal is picked up automatically from the prebuilt wheel.

## Usage

```bash
# Open the welcome screen
python main.py

# Open a PDF directly
python main.py document.pdf
```

For each opened PDF a folder is created at `~/.local/share/pyxis/notes/<pdf-name>/` (Linux) or `%APPDATA%\pyxis\notes\<pdf-name>\` (Windows) containing:

- `notes.md` — editable Markdown notes
- `highlights/` — image snippets of highlighted text
- `captures/` — image snippets of screen captures
- `annotations.json` — metadata index + cached image descriptions

### AI menu (toolbar → AI)

| Command | What it does |
|---------|--------------|
| Load AI Model | Detects RAM/accel, downloads a fitting Gemma 4 GGUF, loads in-process |
| Summarize Notes | Markdown bullet summary of the whole `notes.md` |
| Summarize Current Page | Bullet summary of the page in view |
| Ask… | Free-form Q&A grounded in your PDF via RAG (with page citations) |
| Extract To-Dos | Markdown checklist of action items |
| Draft Follow-up | A short connecting note |
| Suggest Tags | A line of `#tag` tokens |

AI output is streamed live into the notes panel and saved like any other note. `Esc` cancels an active run.

### Accessibility (🎧 toolbar button or Ctrl+Shift+A)

| Shortcut | Action |
|----------|--------|
| `R` | Read current page aloud (TTS) |
| `S` | Stop narration |
| `Space` / `P` | Pause/resume narration |
| `I` | Describe next image on current page (vision model) |
| `N` | Read notes panel aloud |
| `Alt+Left/Right` | Navigate pages (stops narration first) |

Right-clicking an image region triggers description immediately.

### General Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open file |
| `Ctrl+0` | Toggle fit-to-width |
| `Ctrl+=` / `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Alt+Right` | Next page |
| `Alt+Left` | Previous page |
| `Esc` | Clear search / cancel capture / cancel AI / stop narration |

## Tech Stack

Python, [PyQt6](https://riverbankcomputing.com/software/pyqt/), [PyMuPDF](https://pymupdf.readthedocs.io/), [llama.cpp](https://github.com/ggml-org/llama.cpp) (via `llama-cpp-python`), [Gemma 4](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF) (multimodal), [Piper TTS](https://github.com/rhasspy/piper).

## License

MIT
