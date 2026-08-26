# Accessibility

Pyxis is built first and foremost for blind and low-vision readers. Every
PDF can be narrated end-to-end with neural text-to-speech, and every image
on every page is described aloud by the on-device vision model — no cloud,
no API keys, no telemetry.

## Turning it on

- Click the 🎧 toolbar button, **or**
- Press `Ctrl+Shift+A`.

The first time accessibility mode is enabled, Pyxis downloads a ~65 MB
Piper neural voice file (one-time, cached afterwards). On the same machine
the voice is never re-downloaded.

When accessibility mode is on, a secondary toolbar appears below the main
one with **Speed** (0.5×–2.0×) and **Volume** (0–100%) sliders, plus
Pause / Stop / Continue / Help buttons.

## Keyboard shortcuts

These shortcuts are active only while accessibility mode is on.

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+A` | Toggle accessibility mode on/off |
| `Space` / `P` | Pause or resume narration |
| `R` | Read the current page from the start |
| `C` | Continue reading from your saved position (works across sessions) |
| `S` | Stop narration and clear the queue |
| `I` | Describe the next image on the current page (vision model) |
| `N` | Read the notes panel aloud |
| `?` | Open this help window and read it aloud |
| `Esc` | Stop narration / cancel AI / clear search |
| `Alt + ←/→` | Go to the previous / next page (stops narration first) |

Right-clicking an image region on a page triggers an immediate description.

## How it works

- **Paragraph & table text** is sent straight to Piper TTS.
- **Image regions** are sent to the on-device Gemma 4 vision model; the
  generated caption is appended to that PDF's notes and spoken aloud.
- Image descriptions are **cached** per PDF (in `annotations.json`), so
  re-opening a document never re-runs the model.
- Your narration position is persisted per PDF, so `C` ("Continue
  reading") resumes exactly where you left off — even after closing and
  reopening the app.

## Data location

Per-PDF data lives under your OS data directory:

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/pyxis/notes/<pdf-name>/` |
| Windows | `%APPDATA%\pyxis\notes\<pdf-name>\` |
| macOS | `~/Library/Application Support/pyxis/notes/<pdf-name>/` |

Each folder contains `notes.md`, `highlights/`, `captures/`, and
`annotations.json` (which stores cached image descriptions and the
narration resume position).
