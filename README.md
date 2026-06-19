# AI-PDF

A fast, native PDF reader with a graphical interface, built in Python.

## Features

- **Native PDF rendering** via PyMuPDF (MuPDF)
- **Page-by-page scrolling** with LRU render cache
- **Full-text search** across all pages
- **Bookmark / table of contents** navigation in sidebar
- **Zoom controls** with predefined levels (25%–400%) and fit-to-width mode
- **Text highlights** — saved as images per PDF and stored in a notes markdown file
- **Screen captures** — saved as images per PDF and embedded into notes
- **Notes panel** — editable Markdown notes for each PDF (Obsidian-style)
- **Keyboard shortcuts** for all common actions
- **Dark theme** by default
- **Cross-platform** — Linux, macOS, Windows

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/anomalyco/ai-pdf.git
cd ai-pdf
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
# Open the welcome screen
python main.py

# Open a PDF directly
python main.py document.pdf
```

For each opened PDF a folder is created at `notes/<pdf-name>/` containing:

- `notes.md` — editable Markdown notes
- `highlights/` — image snippets of highlighted text
- `captures/` — image snippets of screen captures
- `annotations.json` — metadata index

### Quick Action Menu (right-click)

- **Selected text:** Copy / Add to Notes
- **Existing highlight:** Remove Highlight
- **Empty area:** Capture Screen

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open file |
| `Ctrl+0` | Toggle fit-to-width |
| `Ctrl+=` / `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Alt+Right` | Next page |
| `Alt+Left` | Previous page |
| `Esc` | Clear search / cancel capture |

## Tech Stack

Python, [PyQt6](https://riverbankcomputing.com/software/pyqt/), [PyMuPDF](https://pymupdf.readthedocs.io/)

## License

MIT
