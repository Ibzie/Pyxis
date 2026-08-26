# Pyxis QA Sweep — Epics & Tickets

Generated 2026-08-22 by a 12-agent QA workflow (6 specialist reviewers + 6 adversarial verifiers, each verifier
independently tried to *refute* every bug claim before it's listed here) plus a manual hands-on repro against a
real document (`k3_tech_report.pdf`). Every ticket below is either (a) confirmed by re-reading the exact cited
code, or (b) confirmed by an actual reproduction (offscreen Qt run, synthetic/real PDF, or a minimal script) —
never speculation. One claim ("closing the app while an AI worker is loading crashes with SIGABRT") was
investigated, could not be reproduced in three independent attempts, and was dropped — see **Investigated, not
confirmed** at the bottom.

Not committed/pushed — for you to triage into GitHub issues yourself. Severity: 🔴 critical · 🟠 high · 🟡 medium · ⚪ low.

---

## Epic A — Accessibility & TTS core reliability
*This is the product's core value prop for blind users — these bugs mean the headline feature is currently broken in several ways.*

- **A1** 🔴 **`R`/`C` keys crash narration entirely — `self._narrator` instance attribute shadows the `_narrator()` method**
  `MainWindow.__init__` sets `self._narrator = None` (`main.py:71`), but the class also defines `def _narrator(self):` (`main.py:778-789`) as a lazy getter that's supposed to build the `NarratorWorker`. Because a plain instance attribute always wins over a same-named method in Python's attribute lookup, `self._narrator` is permanently `None`. Every call site (`main.py:804, 822, 827`) does `self._narrator()` → `TypeError: 'NoneType' object is not callable`. Reproduced live: pressing `R` or `C` throws every time.
  *Fix: rename the instance attribute (e.g. `self._narrator_worker`) so it stops shadowing the method.*

- **A2** 🟠 **"Continue reading" resume position races ahead of actual playback — can silently skip content**
  `NarratorWorker._narrate_page` (`narrator.py:93-108`) emits `chunk_progress`/`page_done` right after *enqueueing* text to the (non-blocking) `SpeechQueue`, not after it's actually spoken. `MainWindow` persists that position to disk immediately (`main.py:876-889`). Stopping/closing while chunk 0 is still playing leaves the saved resume point at or past the end of the page — reopening later skips unheard content.

- **A3** 🟠 **Escape's stop-narration/cancel-AI priority is wrong, and Stop-via-Escape doesn't work at all on the pyttsx3 fallback engine**
  `main.py:1016-1025`'s Escape handler always favors stop-narration over cancel-AI when both are running (since `_run_ai` never checks a11y state), so cancelling a stuck AI run needs two Escape presses. Separately, `Pyttsx3Engine.is_speaking()` (`speech.py:196-197`) is hardcoded `return False` — so whenever Piper is unavailable and the app silently falls back to pyttsx3, Escape can *never* stop narration for that user; it falls through to AI-cancel or clear-search instead.

- **A4** 🟠 **No audible confirmation for toggling accessibility mode, or for any of ~50 status/error messages**
  `_a11y_on()`/`_a11y_off()` (`main.py:731-776`) and every other status branch in the app call `self.status.showMessage(...)` (a purely visual `QStatusBar` update) — never `speech_queue.enqueue(...)`. 50 `showMessage` call sites vs. 8 total `enqueue` calls app-wide, none attached to a11y-toggle or generic status/error text. A blind user flipping a11y on/off, or hitting a gated error like "Load an AI model first", gets zero self-produced audio feedback.

- **A5** 🟡 **Accessibility toolbar button's checked/pressed visual state desyncs from real state when toggled via `Ctrl+Shift+A`**
  The 🎧 toggle button is created inline with no stored reference (`main.py:123-124`); `toggle_a11y()` has no widget handle to call `setChecked(...)` on. Toggling via the keyboard shortcut leaves the toolbar button showing the *opposite* of the true a11y state.

- **A6** 🟠 **No accessible names on any toolbar button/slider — invisible to real OS screen readers (Orca/NVDA/VoiceOver), including the 🎧 button that's the only way to discover a11y mode**
  Zero uses of `setAccessibleName`/`setAccessibleDescription`/`QAccessible` anywhere in the codebase; only 2 `setToolTip` calls total (the a11y sliders). 11 icon-only toolbar buttons (`◀ ▶ − + ⊞ ↓ ↑ ✕ ☰ 📝 🎧`) announce only raw glyphs to a screen reader tabbing through the toolbar — before Pyxis's own accessibility mode is even discoverable.

- **A7** ⚪ **No in-app discovery path for a11y mode or its shortcuts** — and a good low-effort fix already sketched: **speak the Accessibility Help aloud automatically the first time a11y mode is ever turned on** (reuse the existing `_show_a11y_help()` / `A11Y_KEYBINDS`, gated by a one-time "onboarded" flag).

- **A8** 🟠 **"Read current page" / "Continue reading" are needlessly gated behind a fully-loaded LLM + completed RAG index**, even though `NarratorWorker` already has a working plain-text (PyMuPDF) fallback that needs neither (`narrator.py:82-92`). Right now the single most basic accessibility action is blocked behind downloading/loading a multi-GB model.

- **A9** 🔴 **Enabling accessibility mode freezes the whole UI during the first-run Piper voice download (~65MB, no threading, no progress bar)** — `PiperEngine.__init__` runs two blocking `hf_hub_download()` calls directly on the GUI thread (`speech.py:75-102`), unlike the Gemma model loader which is correctly wrapped in a `QThread` with progress signals (`ai_workers.py:5-28`). On a fresh machine or after a cache clear, the window appears hung for the whole download.

- **A10** 🟡 *(feature)* **Export page/document narration as a standalone WAV file** — `PiperEngine.speak()` already produces raw int16 PCM per sentence (`speech.py:129`); redirecting those frames to a `wave.open()` writer (instead of/alongside live playback) is a small, well-scoped addition.

- **A11** ⚪ *(feature)* **Adjustable UI font size / high-contrast palette for low-vision (not just blind) users** — currently one hardcoded dark `QPalette` + scattered fixed `font-size` CSS (`notes_panel.py:262`), with no text-scale or alternate-contrast mechanism, unlike the PDF page zoom which already exists.

---

## Epic B — Notes editor: WYSIWYG correctness & data integrity
*Directly addresses your "notes section is unrendered markdown while editing" complaint — some constructs genuinely aren't handled, and there are real corruption bugs around inline images.*

- **B1** 🔴 **Deleting one of several inline images silently reassigns a *different* image's markdown to the wrong picture, corrupting `notes.md` on the very next autosave.**
  `_on_edit()`'s image-reconciliation (`notes_panel.py:438-456`) matches images to markdown purely by *count*, and on deletion always drops the **last** tracked entry (`self._image_list[:n_imgs]`) regardless of which image was actually removed. Reproduced directly: deleting the *first* of two images left the still-present second image mislabeled with the first image's file path.

- **B2** 🟠 **Pasting text containing a literal U+FFFC character discards image tracking and corrupts the saved note.** Reproduced: inserting `"pasted ￼ stray char"` into a note with one tracked image caused `_source` to lose the real image markdown entirely, replaced by an inert placeholder glyph. Autosave (fires every keystroke) then bakes the corruption into `notes.md`.

- **B3** 🟠 **Hidden markdown markers are ordinary editable characters — placing the cursor between them and typing un-hides the rest of the construct as raw, visible markdown.** `_invisible()` (`notes_panel.py:69-72`) only recolors marker characters to match the background; they're still normal cursor-navigable positions. Reproduced: typing inside `**bold**`'s opening marker turned it into `*X*bold**`, which re-parses as an italic run followed by fully-visible raw `bold**` text.

- **B4** 🟠 **"Read notes aloud" (`N`) speaks raw Markdown syntax verbatim** — `get_text()` returns the raw source unmodified, and there is no markdown-to-speech cleanup anywhere in the app. A blind user pressing `N` hears literal `#`, `**`, `- [ ]`, and full image file paths instead of clean prose.

- **B5** 🟡 **The live WYSIWYG highlighter is missing rules for several common constructs that PDF export *does* support**: fenced code blocks (```` ``` ````), tables (even though `.enable("table")` is on for export), plain (non-checkbox) bullet lists, ordered lists, strikethrough, and multi-line `$$...$$` block math that spans more than one line (the highlighter only sees one line/block at a time). These render as fully raw, unstyled markdown in the editor — this is very likely the main thing behind "it's unrendered markdown while editing."

- **B6** 🟡 **Autosave has no debounce and writes the entire file non-atomically on every single keystroke.** `textChanged` → `_on_edit` → callback → `storage.save_notes()` → `Path.write_text()` (truncate-then-write, no temp-file+rename) fires on every keystroke with no timer. A crash/power-loss mid-write has an unusually large exposure window to truncate `notes.md`. (The one debounce timer that exists in this file is wired only to AI-streaming output, not typing.)

- **B7** ⚪ **A broken/missing inline image reference is left as ambiguous dimmed raw markdown text**, with no distinct "image failed to load" indicator to tell it apart from intentionally-unrendered syntax.

---

## Epic C — Notes PDF export never embeds images (confirmed root cause, reproduced against your real PDF)
*This is your "image export properly in notes" complaint — it is a real, currently-broken bug, not a stale worry. One reviewer initially concluded it was already fixed by only checking that the code's URL-matching logic was internally consistent; it hadn't actually run the render step. Three independent reproductions (two agents + my own manual test) prove it's broken.*

- **C1** 🔴 **`export_pdf()` always prints the literal `![alt](file:///abs/path.png)` text instead of the image bitmap — for every local image, unconditionally.**
  Root cause: `_resolve()` (`notes_panel.py:350-358`) rewrites relative image paths to `file://` URIs before handing the text to `render_markdown_html()`. But `markdown-it-py`'s built-in link/image destination validator (`BAD_PROTO_RE` in `markdown_it/common/normalize_url.py`) **unconditionally rejects the `file:` scheme** (it's a security denylist against `javascript:`/`vbscript:`/`file:`/`data:` URIs) — so `![alt](file:///...)` is never parsed into an `<img>` tag at all; it stays as literal unparsed text. The `QTextDocument.addResource(...)` pre-registration in `export_pdf()` therefore has nothing to bind to and is silently unused.
  **I personally reproduced this end-to-end against your real `k3_tech_report.pdf`**: rendered page 3 of the actual PDF to a PNG (simulating a real capture), built a note referencing it via the real `PdfStorage`/`NotesPanel` code, and called the real `export_pdf()` logic headlessly. Screenshot of the **live editor** shows the captured PDF page image rendered correctly inline. Screenshot of the **exported PDF** shows the literal text `![capture from page 3](file:///home/.../captures/cap_p2_test.png)` instead of the image — confirming the bug is real, current, and reproducible with a real document, not just a synthetic test string. Isolated `markdown-it` bisection confirms: `![alt](/tmp/x.png)` → proper `<img>`; `![alt](file:///tmp/x.png)` → literal text, in every plugin combination the app uses.
  *Fix: don't rewrite paths to `file://` URIs before parsing — pass plain absolute filesystem paths (which `markdown-it` parses fine and Qt also resolves), or construct the `MarkdownIt` instance with a custom `validateLink` that allows `file:`.*
  *Related edge case surfaced during review: if the image file is missing, the resource-registration loop skips it, but `_resolve()` still rewrites the link to a `file://` URI — worth handling in the same fix.*

---

## Epic D — New feature: Whiteboard tab
*You asked for this explicitly. Confirmed by 5 independent reviewers: there is zero drawing/canvas code anywhere in the repo, and the right-hand panel is a single fixed `NotesPanel` widget added directly to the main `QSplitter` — not a `QTabWidget`. So this is genuinely new work, not a toggle.*

- **D1** 🟡 *(feature)* **Add a Whiteboard tab alongside Notes.** Concretely: wrap the existing `NotesPanel` in a `QTabWidget` (Notes / Whiteboard), add a new `QWidget`-based freehand-drawing canvas (a `QPixmap` + `QPainter` strokes, matching the app's existing plain-widget+`QPainter` style already used in `page_view.py`), with a small pen/eraser/color/clear toolbar. Persist per-PDF as a flattened PNG in the existing `notes/<pdf-name>/` folder (fits the project's existing highlights/captures convention better than a vector stroke log, matching the "no tests, zero-config" style). Make `export_pdf()` tab-aware so whiteboard content isn't silently dropped from notes PDF exports.

---

## Epic E — AI layer: correctness & concurrency
- **E1** 🟠 **Switching AI model tier mid-inference double-loads a model without freeing the old one.** `_load_ai()` only guards against a second *load* running, never against an in-flight *inference* (`main.py:595-611` vs. the symmetric guard in `_run_ai`, `main.py:673-688`). The old `Llama` instance stays resident (still referenced by the running inference's generator) alongside the newly-loaded one — a real memory spike on RAM-constrained demo hardware.

- **E2** 🟠 **"Describe image" (`I` / right-click) has no re-entrancy guard and can race narration on the single shared `Llama` instance** — no lock anywhere protects concurrent `create_chat_completion()` calls; `_describe_image_at`, `NarratorWorker`, and the AI-ask path can all hit the same model object at once (e.g. pressing `I` twice quickly, or asking a question mid-narration-of-an-image).

- **E3** 🟡 **The advertised automatic NVIDIA CUDA acceleration is dead code.** `ensure_gpu_native()` is fully implemented (`ai_layer.py:97-159`) but has zero call sites anywhere, including inside `load_model()` — and would itself raise `NameError` if ever called (`sys` isn't imported at module scope; confirmed by directly invoking it). README.md and `packaging/README.md` both describe this feature in detail; on an NVIDIA machine the app silently stays CPU-only.

- **E4** 🟡 **No way to cancel a stalled/slow model download** — only in-flight *inference* has a cancel path (`Esc` checks `ai_infer`, never `ai_loader`), and even a UI hook would have nothing to call since the download code never consults `self._cancel`. On flaky hackathon wifi, a hung multi-GB download has no recourse but waiting.

- **E5** ⚪ **RAG context budget is character-based (`budget=12000`), not token-based, and can silently exceed the model's real `N_CTX=8192` token window** for token-dense content (tables, code, non-Latin text).

- **E6** ⚪ **A cancelled AI run still reports "finished_ok" with no distinction from a completed run** — the truncated output is saved to notes and shown identically to a full answer, no "cancelled — may be incomplete" marker.

---

## Epic F — Core PDF reader: crash safety & navigation
- **F1** 🔴 **Whole app hard-crashes (SIGABRT) if `Ctrl+0` is pressed twice before opening any PDF.** `_apply_zoom()` indexes `self.engine.page_sizes[0][0]` unconditionally; with no PDF loaded that list is empty. Reproduced live: two genuine `Ctrl+0` key events → `IndexError` → process exit code 134.

- **F2** 🔴 **No global exception handler anywhere — any uncaught exception in a Qt slot kills the entire process instantly, discarding unsaved notes.** Only 3 real `except` blocks exist in all of `main.py`'s 1128 lines; there is no `sys.excepthook` and no wrapper around `app.exec()`. F1 above is a live demonstration of exactly this.

- **F3** 🟠 **Keyboard scrolling (arrow keys, PageUp/PageDown, Home/End) doesn't work anywhere in the document view.** `PageView` never calls `setFocus()` on click, and `MainWindow.keyPressEvent` has no handling for these keys — the scroll area's own built-in key handling is fully functional but unreachable because nothing ever routes focus to it. Reproduced live (manually focusing the scroll area proves the underlying scroll logic works fine).

- **F4** 🟠 **Fit-to-width zoom is computed only from page 0's width and applied uniformly** — a document with mixed page sizes renders every other page at the wrong on-screen width. Reproduced with a 4-page test PDF containing one landscape page: it rendered at exactly 2× the correct width.

- **F5** 🟠 **Zoom/resize eagerly re-renders every page in the document (ignoring viewport visibility) and fully clears the LRU render cache every time**, including on every `resizeEvent` fired continuously during a live window-resize drag while fit-to-width is on. Reproduced with a 60-page test PDF: a single resize event triggered 60 full re-renders. On larger documents (`MAX_CACHE=50`) this can visibly freeze the UI.

- **F6** 🟡 **Search finds the right pages but never highlights the matched text on-page**, and folds multiple in-page hits into a single result in the "1/N" counter.

- **F7** ⚪ **Latent bug: `render_page`'s non-RGB(A) pixmap branch would mis-decode the image buffer** (assumes `Format_RGBA8888` regardless of actual channel count) — currently unreachable since the app always requests RGB, but should convert/branch explicitly rather than silently mismatch format-to-buffer if that ever changes.

---

## Epic G — Storage & data safety
- **G1** 🟠 **Opening a PDF when the data directory isn't writable crashes the whole app** — `load_pdf()`'s try/except only wraps `PdfEngine.open()`; the next line, `PdfStorage(path)` (which does an unguarded `mkdir`), is outside it. Reproduced: a read-only data directory raises an uncaught `PermissionError`. Combined with F2 (no global handler), this SIGABRTs the process.

- **G2** 🟠 **Filename sanitization collides distinct documents into one notes folder, leaking one PDF's notes/highlights into another's.** `_safe_name()` maps every non-alphanumeric character to `_` with no collision check — reproduced directly: `"a b.pdf"` and `"a_b.pdf"` both sanitize to the identical folder name.

- **G3** 🟠 **No locking on `notes.md`/`annotations.json` — opening the same PDF twice (or two instances) causes a silent lost-update race.** Both files are loaded once into memory and every save blindly overwrites the whole file from that stale in-memory snapshot, with no re-read-and-merge.

- **G4** 🟠 **`notes.md`/`annotations.json` are written non-atomically** (`Path.write_text()` truncates immediately, no temp-file+rename) — a crash or kill mid-save can destroy the file rather than just losing the latest edit.

- **G5** 🟡 **Password-protected PDFs are unconditionally rejected with no password-entry UI** — the failure is caught gracefully (no crash), but there's no retry-with-password path.

---

## Epic H — Product & hackathon-demo polish
- **H1** 🟠 **README's accessibility shortcut table is missing two real, working shortcuts** (`C` — continue reading cross-session, `?` — accessibility help) that exist in code and in `AGENTS.md`. A judge reading only the public README would miss the "resume where I left off" feature entirely.
- **H2** 🟡 **No visible progress indicator for either first-run download** (multi-GB AI model, ~65MB voice) beyond status-bar text; the voice download additionally blocks the UI thread entirely (see **A9**).

---

## Investigated, not confirmed
- **"Closing the app while an AI model is still loading crashes with SIGABRT."** The underlying design gap is real (no cooperative cancellation in the model loader; `closeEvent` doesn't confirm actual thread termination before unloading) and is worth keeping in mind, but three independent, faithful reproduction attempts — including driving the real `MainWindow.closeEvent()` against a real in-flight `LoadWorker` — never produced a crash. Not filed as a ticket; flagging here so it isn't rediscovered and re-litigated without cause.
