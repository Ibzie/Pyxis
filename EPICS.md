# Pyxis QA Sweep — Epics & Tickets

Generated 2026-08-22 by a 12-agent QA workflow (6 specialist reviewers + 6 adversarial verifiers, each verifier
independently tried to *refute* every bug claim before it's listed here) plus a manual hands-on repro against a
real document (`k3_tech_report.pdf`). Every ticket below is either (a) confirmed by re-reading the exact cited
code, or (b) confirmed by an actual reproduction (offscreen Qt run, synthetic/real PDF, or a minimal script) —
never speculation. One claim ("closing the app while an AI worker is loading crashes with SIGABRT") was
investigated, could not be reproduced in three independent attempts, and was dropped — see **Investigated, not
confirmed** at the bottom.

Not committed/pushed — for you to triage into GitHub issues yourself. Severity: 🔴 critical · 🟠 high · 🟡 medium · ⚪ low.

## Status (updated 2026-08-30)

Batch 4 — remaining features + data-safety close-out (all epics now complete):
**A10 · A11 · D1 · G3 · G5 · H2** — each marked `✅ RESOLVED` below.

Batch 3 — AI-layer concurrency/correctness + reader rendering/search:
**E1 · E2 · E3 · E4 · E5 · E6 · F4 · F5 · F6 · F7** — each marked `✅ RESOLVED` below.

Batch 2 — accessibility reliability + data safety + keyboard navigation:
**A2 · A3 · A4 · A5 · A6 · A7 · A8 · F3 · G2 · G4** — each marked `✅ RESOLVED` below.

Earlier fixes (batch 1 — repo restructure + crash fixes + notes-editor rewrite):
**A1 · A9 · B1 · B2 · B3 · B4 · B5 · B6 · B7 · C1 · F1 · F2 · G1 · H1** — each marked `✅ RESOLVED` below.

Every ticket in this file is now `✅ RESOLVED`. Tests were headless (offscreen Qt + PyMuPDF) — no formal test suite exists.

---

## Epic A — Accessibility & TTS core reliability

## Epic A — Accessibility & TTS core reliability
*This is the product's core value prop for blind users — these bugs mean the headline feature is currently broken in several ways.*

- **A1** 🔴 **`R`/`C` keys crash narration entirely — `self._narrator` instance attribute shadows the `_narrator()` method** — ✅ **RESOLVED**
  `MainWindow.__init__` sets `self._narrator = None` (`main.py:71`), but the class also defines `def _narrator(self):` (`main.py:778-789`) as a lazy getter that's supposed to build the `NarratorWorker`. Because a plain instance attribute always wins over a same-named method in Python's attribute lookup, `self._narrator` is permanently `None`. Every call site (`main.py:804, 822, 827`) does `self._narrator()` → `TypeError: 'NoneType' object is not callable`. Reproduced live: pressing `R` or `C` throws every time.
  *Fix: rename the instance attribute (e.g. `self._narrator_worker`) so it stops shadowing the method.* — applied: attribute is now `self._narrator_worker` everywhere (`__init__`, `_a11y_off`, `_narrator()`, `closeEvent`).

- **A2** 🟠 **"Continue reading" resume position races ahead of actual playback — can silently skip content** — ✅ **RESOLVED**
  `NarratorWorker._narrate_page` (`narrator.py:93-108`) emits `chunk_progress`/`page_done` right after *enqueueing* text to the (non-blocking) `SpeechQueue`, not after it's actually spoken. `MainWindow` persists that position to disk immediately (`main.py:876-889`). Stopping/closing while chunk 0 is still playing leaves the saved resume point at or past the end of the page — reopening later skips unheard content.
  *Fix: disk persistence now happens only when a chunk actually starts playing. `SpeechQueue.enqueue(text, meta)` tags chunks with `(page, chunk)` and emits `position_started` before speaking; `MainWindow._on_position_played` writes it. The narrator enqueues a silent `_EndMarker` after a page's chunks; when the queue reaches it, every prior chunk has finished, so `page_end` → `_on_page_played_to_end` advances the resume point to the next page top. Verified headless: positions persist only for chunks that were heard; a stopped/closing mid-read never skips content.*

- **A3** 🟠 **Escape's stop-narration/cancel-AI priority is wrong, and Stop-via-Escape doesn't work at all on the pyttsx3 fallback engine** — ✅ **RESOLVED**
  `main.py:1016-1025`'s Escape handler always favors stop-narration over cancel-AI when both are running (since `_run_ai` never checks a11y state), so cancelling a stuck AI run needs two Escape presses. Separately, `Pyttsx3Engine.is_speaking()` (`speech.py:196-197`) is hardcoded `return False` — so whenever Piper is unavailable and the app silently falls back to pyttsx3, Escape can *never* stop narration for that user; it falls through to AI-cancel or clear-search instead.
  *Fixed: `MainWindow` tracks `_esc_target` (set to `"ai"`/`"narration"` when an AI run or narration starts); Esc cancels the most-recently-started active operation first, then falls back to heuristics. `Pyttsx3Engine` now tracks a real `_speaking` flag (set in `speak`, cleared in `cancel`/on exit). Verified headless: with both running, a single Esc cancels AI; with narration tracked, a single Esc stops it.*

- **A4** 🟠 **No audible confirmation for toggling accessibility mode, or for any of ~50 status/error messages** — ✅ **RESOLVED**
  `_a11y_on()`/`_a11y_off()` (`main.py:731-776`) and every other status branch in the app call `self.status.showMessage(...)` (a purely visual `QStatusBar` update) — never `speech_queue.enqueue(...)`. 50 `showMessage` call sites vs. 8 total `enqueue` calls app-wide, none attached to a11y-toggle or generic status/error text. A blind user flipping a11y on/off, or hitting a gated error like "Load an AI model first", gets zero self-produced audio feedback.
  *Fixed: `_a11y_on()` now announces "Accessibility mode on — press R to read, C to continue…" once the voice loads; `_a11y_off()` speaks "Accessibility mode off" before draining and stopping the queue (`flush_and_stop` + `wait`). A new `_speak()` helper routes the key gated errors — "Load an AI model first", "Current model is text-only", "No more images on this page", "AI busy" — through TTS when accessibility is active.*

- **A5** 🟡 **Accessibility toolbar button's checked/pressed visual state desyncs from real state when toggled via `Ctrl+Shift+A`** — ✅ **RESOLVED**
  The 🎧 toggle button is created inline with no stored reference (`main.py:123-124`); `toggle_a11y()` has no widget handle to call `setChecked(...)` on. Toggling via the keyboard shortcut leaves the toolbar button showing the *opposite* of the true a11y state.
  *Fixed: the button is stored as `self.a11y_toggle_btn` and `toggle_a11y()` syncs `setChecked(self._a11y_mode)` on every path (including `_on_voice_failed`). Verified headless.*

- **A6** 🟠 **No accessible names on any toolbar button/slider — invisible to real OS screen readers (Orca/NVDA/VoiceOver), including the 🎧 button that's the only way to discover a11y mode** — ✅ **RESOLVED**
  Zero uses of `setAccessibleName`/`setAccessibleDescription`/`QAccessible` anywhere in the codebase; only 2 `setToolTip` calls total (the a11y sliders). 11 icon-only toolbar buttons (`◀ ▶ − + ⊞ ↓ ↑ ✕ ☰ 📝 🎧`) announce only raw glyphs to a screen reader tabbing through the toolbar — before Pyxis's own accessibility mode is even discoverable.
  *Fixed: every toolbar button is now built through a `_btn()` helper that sets `setAccessibleName` + `setToolTip` ("Previous page", "Toggle accessibility mode (Ctrl+Shift+A)", …), plus the a11y-bar speed/volume sliders and Pause/Stop/Continue/Help buttons. Verified headless: all names present.*

- **A7** ⚪ **No in-app discovery path for a11y mode or its shortcuts** — and a good low-effort fix already sketched: **speak the Accessibility Help aloud automatically the first time a11y mode is ever turned on** (reuse the existing `_show_a11y_help()` / `A11Y_KEYBINDS`, gated by a one-time "onboarded" flag). — ✅ **RESOLVED**
  *Applied: `storage.a11y_onboarded()`/`mark_a11y_onboarded()` (a flag file in the app-data dir); `_on_voice_ready` enqueues the full `A11Y_KEYBINDS` list aloud the first time a11y mode is ever enabled, so the shortcuts are discoverable without a screen reader.*

- **A8** 🟠 **"Read current page" / "Continue reading" are needlessly gated behind a fully-loaded LLM + completed RAG index**, even though `NarratorWorker` already has a working plain-text (PyMuPDF) fallback that needs neither (`narrator.py:82-92`). Right now the single most basic accessibility action is blocked behind downloading/loading a multi-GB model. — ✅ **RESOLVED**
  *Fixed: the `ai.is_loaded()`/`rag_index.is_ready` gates were removed from `_read_current_page()` and `_continue_reading()`; `_narrate_page` handles `rag=None` (falls back to raw page text; a "continue" with no index re-reads from the page top) and image chunks degrade to "Image present but vision model not loaded" instead of failing. Verified headless: pressing R narrates a real PDF with no AI model and no index.*

- **A9** 🔴 **Enabling accessibility mode freezes the whole UI during the first-run Piper voice download (~65MB, no threading, no progress bar)** — ✅ **RESOLVED** — `PiperEngine.__init__` runs two blocking `hf_hub_download()` calls directly on the GUI thread (`speech.py:75-102`), unlike the Gemma model loader which is correctly wrapped in a `QThread` with progress signals (`ai_workers.py:5-28`). On a fresh machine or after a cache clear, the window appears hung for the whole download.
  *Fixed: the voice download now runs in a `VoiceLoadWorker` QThread (`speech.py`), started by `_a11y_on()`; `_a11y_on()` returns immediately (measured ~0ms) and binds the `SpeechQueue` via the `done` signal. `R`/`C`/`N` show "TTS voice still loading…" until ready; `closeEvent` waits for the worker.*

- **A10** 🟡 *(feature)* **Export page/document narration as a standalone WAV file** — `PiperEngine.speak()` already produces raw int16 PCM per sentence (`speech.py:129`); redirecting those frames to a `wave.open()` writer (instead of/alongside live playback) is a small, well-scoped addition. — ✅ **RESOLVED**
  *Applied: `PiperEngine.render_wav(text, path)` writes the same synthesized frames to a WAV file (mono, 16-bit, engine sample rate); a `WavExportWorker` QThread renders off the GUI thread; the a11y bar gained a "⏺ Save Audio" button wired to `_export_page_wav()` which saves the current page's narration. Verified headless: the worker produces a valid WAV (correct frame rate/frame count). Piper-only — pyttsx3 has no offline render path and reports that clearly.*

- **A11** ⚪ *(feature)* **Adjustable UI font size / high-contrast palette for low-vision (not just blind) users** — currently one hardcoded dark `QPalette` + scattered fixed `font-size` CSS (`notes_panel.py:262`), with no text-scale or alternate-contrast mechanism, unlike the PDF page zoom which already exists. — ✅ **RESOLVED**
  *Applied: an "Aa" toolbar button opens a UI-settings dialog with a font-size slider and a high-contrast (pure black/white) checkbox; settings persist to `app_data_dir/settings.json`. `_apply_app_palette` swaps the whole-app palette, the notes editor font scales via `NotesPanel.set_ui_scale`, and the window stylesheet switches to black/white. Verified headless: settings round-trip; MainWindow wires the controls.*

---

## Epic B — Notes editor: WYSIWYG correctness & data integrity
*Directly addresses your "notes section is unrendered markdown while editing" complaint — some constructs genuinely aren't handled, and there are real corruption bugs around inline images.*

- **B1** 🔴 **Deleting one of several inline images silently reassigns a *different* image's markdown to the wrong picture, corrupting `notes.md` on the very next autosave.** — ✅ **RESOLVED**
  `_on_edit()`'s image-reconciliation (`notes_panel.py:438-456`) matches images to markdown purely by *count*, and on deletion always drops the **last** tracked entry (`self._image_list[:n_imgs]`) regardless of which image was actually removed. Reproduced directly: deleting the *first* of two images left the still-present second image mislabeled with the first image's file path.
  *Fixed by design in the rewrite: each logical block's raw markdown is independent (`_block_raw`), images only render inside non-focused blocks, and the editable block shows raw `![alt](path)` text — deleting one image can never relabel another. Verified headless (delete first of two images → second intact).*

- **B2** 🟠 **Pasting text containing a literal U+FFFC character discards image tracking and corrupts the saved note.** Reproduced: inserting `"pasted ￼ stray char"` into a note with one tracked image caused `_source` to lose the real image markdown entirely, replaced by an inert placeholder glyph. Autosave (fires every keystroke) then bakes the corruption into `notes.md`. — ✅ **RESOLVED** — `_WysiwygEdit.insertFromMimeData` now strips U+FFFC from pasted text (B2); the rewrite no longer uses U+FFFC object chars in the editable source at all.

- **B3** 🟠 **Hidden markdown markers are ordinary editable characters — placing the cursor between them and typing un-hides the rest of the construct as raw, visible markdown.** `_invisible()` (`notes_panel.py:69-72`) only recolors marker characters to match the background; they're still normal cursor-navigable positions. Reproduced: typing inside `**bold**`'s opening marker turned it into `*X*bold**`, which re-parses as an italic run followed by fully-visible raw `bold**` text. — ✅ **RESOLVED** — the `QSyntaxHighlighter` recolor approach was removed entirely; non-focused blocks are rendered fragments with **no marker characters present**, and the focused block shows raw markdown by design. Nothing to "un-hide".

- **B4** 🟠 **"Read notes aloud" (`N`) speaks raw Markdown syntax verbatim** — `get_text()` returns the raw source unmodified, and there is no markdown-to-speech cleanup anywhere in the app. A blind user pressing `N` hears literal `#`, `**`, `- [ ]`, and full image file paths instead of clean prose. — ✅ **RESOLVED** — `NotesPanel.get_plain_text()` projects markdown to prose (strips headers/markers, unwraps links, replaces images with alt text, drops fenced code); `MainWindow._read_notes_aloud` uses it.

- **B5** 🟡 **The live WYSIWYG highlighter is missing rules for several common constructs that PDF export *does* support**: fenced code blocks (```` ``` ````), tables (even though `.enable("table")` is on for export), plain (non-checkbox) bullet lists, ordered lists, strikethrough, and multi-line `$$...$$` block math that spans more than one line (the highlighter only sees one line/block at a time). These render as fully raw, unstyled markdown in the editor — this is very likely the main thing behind "it's unrendered markdown while editing." — ✅ **RESOLVED** — the editor renders every block through `render_markdown_html` (markdown-it with table/strikethrough/math plugins), so all these constructs render live.

- **B6** 🟡 **Autosave has no debounce and writes the entire file non-atomically on every single keystroke.** `textChanged` → `_on_edit` → callback → `storage.save_notes()` → `Path.write_text()` (truncate-then-write, no temp-file+rename) fires on every keystroke with no timer. A crash/power-loss mid-write has an unusually large exposure window to truncate `notes.md`. (The one debounce timer that exists in this file is wired only to AI-streaming output, not typing.) — ✅ **RESOLVED** — `NotesPanel` debounces saves (300 ms single-shot timer); `storage.save_notes()` writes atomically (temp file + `fsync` + `os.replace`).

- **B7** ⚪ **A broken/missing inline image reference is left as ambiguous dimmed raw markdown text**, with no distinct "image failed to load" indicator to tell it apart from intentionally-unrendered syntax. — ✅ **RESOLVED** — `_resolve_block`/`_resolve_full` leave missing image refs as relative paths (not `file://` URIs), which render as an unresolved `<img>` (broken-image placeholder) in the live view/export instead of ambiguous dimmed text.

---

## Epic C — Notes PDF export never embeds images (confirmed root cause, reproduced against your real PDF)
*This is your "image export properly in notes" complaint — it is a real, currently-broken bug, not a stale worry. One reviewer initially concluded it was already fixed by only checking that the code's URL-matching logic was internally consistent; it hadn't actually run the render step. Three independent reproductions (two agents + my own manual test) prove it's broken.*

- **C1** 🔴 **`export_pdf()` always prints the literal `![alt](file:///abs/path.png)` text instead of the image bitmap — for every local image, unconditionally.** — ✅ **RESOLVED**
  Root cause: `_resolve()` (`notes_panel.py:350-358`) rewrites relative image paths to `file://` URIs before handing the text to `render_markdown_html()`. But `markdown-it-py`'s built-in link/image destination validator (`BAD_PROTO_RE` in `markdown_it/common/normalize_url.py`) **unconditionally rejects the `file:` scheme** (it's a security denylist against `javascript:`/`vbscript:`/`file:`/`data:` URIs) — so `![alt](file:///...)` is never parsed into an `<img>` tag at all; it stays as literal unparsed text. The `QTextDocument.addResource(...)` pre-registration in `export_pdf()` therefore has nothing to bind to and is silently unused.
  **I personally reproduced this end-to-end against your real `k3_tech_report.pdf`**: rendered page 3 of the actual PDF to a PNG (simulating a real capture), built a note referencing it via the real `PdfStorage`/`NotesPanel` code, and called the real `export_pdf()` logic headlessly. Screenshot of the **live editor** shows the captured PDF page image rendered correctly inline. Screenshot of the **exported PDF** shows the literal text `![capture from page 3](file:///home/.../captures/cap_p2_test.png)` instead of the image — confirming the bug is real, current, and reproducible with a real document, not just a synthetic test string. Isolated `markdown-it` bisection confirms: `![alt](/tmp/x.png)` → proper `<img>`; `![alt](file:///tmp/x.png)` → literal text, in every plugin combination the app uses.
  *Fix: don't rewrite paths to `file://` URIs before parsing — pass plain absolute filesystem paths (which `markdown-it` parses fine and Qt also resolves), or construct the `MarkdownIt` instance with a custom `validateLink` that allows `file:`.*
  *Related edge case surfaced during review: if the image file is missing, the resource-registration loop skips it, but `_resolve()` still rewrites the link to a `file://` URI — worth handling in the same fix.*
  *Applied: `render_markdown_html` overrides `md.validateLink` to allow the `file:` scheme (safe — output goes to `QTextDocument`/PDF, never a browser), so `QTextDocument.addResource` binds and the bitmap embeds. `_resolve`/`_resolve_block` now skip missing files. Verified headless: exported PDF contains the image XObject with no literal markdown text.*

---

## Epic D — New feature: Whiteboard tab
*You asked for this explicitly. Confirmed by 5 independent reviewers: there is zero drawing/canvas code anywhere in the repo, and the right-hand panel is a single fixed `NotesPanel` widget added directly to the main `QSplitter` — not a `QTabWidget`. So this is genuinely new work, not a toggle.*

- **D1** 🟡 *(feature)* **Add a Whiteboard tab alongside Notes.** Concretely: wrap the existing `NotesPanel` in a `QTabWidget` (Notes / Whiteboard), add a new `QWidget`-based freehand-drawing canvas (a `QPixmap` + `QPainter` strokes, matching the app's existing plain-widget+`QPainter` style already used in `page_view.py`), with a small pen/eraser/color/clear toolbar. Persist per-PDF as a flattened PNG in the existing `notes/<pdf-name>/` folder (fits the project's existing highlights/captures convention better than a vector stroke log, matching the "no tests, zero-config" style). Make `export_pdf()` tab-aware so whiteboard content isn't silently dropped from notes PDF exports. — ✅ **RESOLVED**
  *Applied: a new `whiteboard.py` (`WhiteboardWidget` + `_Canvas`) draws with a `QPixmap`/`QPainter` buffer and a pen-color/eraser/clear toolbar. The right panel is now a `QTabWidget` (Notes / Whiteboard); strokes autosave (debounced + on tab switch) to `notes/<pdf>/whiteboard.png` and reload on reopen. `NotesPanel.on_export` gives `export_pdf` an extra-markdown hook; `_whiteboard_export_md` appends `![whiteboard](whiteboard.png)` so the canvas embeds in the exported PDF. Verified headless: strokes persist, reload, and produce the expected export markdown.*

---

## Epic E — AI layer: correctness & concurrency
- **E1** 🟠 **Switching AI model tier mid-inference double-loads a model without freeing the old one.** — ✅ **RESOLVED**
  `_load_ai()` only guards against a second *load* running, never against an in-flight *inference* (`main.py:595-611` vs. the symmetric guard in `_run_ai`, `main.py:673-688`). The old `Llama` instance stays resident (still referenced by the running inference's generator) alongside the newly-loaded one — a real memory spike on RAM-constrained demo hardware.
  *Fixed: `_load_ai()` and `_unload_ai()` now both refuse to touch the model while `ai_infer` is running ("AI busy — wait for it to finish (Esc to cancel)"). Verified headless: a model switch attempt during an active inference creates no loader.*

- **E2** 🟠 **"Describe image" (`I` / right-click) has no re-entrancy guard and can race narration on the single shared `Llama` instance** — no lock anywhere protects concurrent `create_chat_completion()` calls; `_describe_image_at`, `NarratorWorker`, and the AI-ask path can all hit the same model object at once (e.g. pressing `I` twice quickly, or asking a question mid-narration-of-an-image). — ✅ **RESOLVED**
  *Fixed: `AILayer` gained a `threading.Lock` (`_infer_lock`) serializing `generate`, `describe_image`, and `expand_query` — one llama call at a time, however many threads (narrator, InferWorker, `_ImgWorker`) try. `_describe_image_at` additionally refuses a second vision call while one is in flight. Verified headless: 3 concurrent `generate` calls touch the model at most once at a time.*

- **E3** 🟡 **The advertised automatic NVIDIA CUDA acceleration is dead code.** — ✅ **RESOLVED**
  `ensure_gpu_native()` is fully implemented (`ai_layer.py:97-159`) but has zero call sites anywhere, including inside `load_model()` — and would itself raise `NameError` if ever called (`sys` isn't imported at module scope; confirmed by directly invoking it). README.md and `packaging/README.md` both describe this feature in detail; on an NVIDIA machine the app silently stays CPU-only.
  *Fixed: `sys`/`Path` are now module-level imports (no more `NameError`); `ensure_gpu_native()` is called from `main()` before the window is created, and on a fresh CUDA-lib download the app auto-restarts via `os.execv` so the native lib loads at import time (falls back to CPU if the restart can't be done).*

- **E4** 🟡 **No way to cancel a stalled/slow model download** — only in-flight *inference* has a cancel path (`Esc` checks `ai_infer`, never `ai_loader`), and even a UI hook would have nothing to call since the download code never consults `self._cancel`. On flaky hackathon wifi, a hung multi-GB download has no recourse but waiting. — ✅ **RESOLVED**
  *Fixed: `_download` now checks `self._cancel` before each file and raises "Download cancelled" (with `reset_cancel()` at the start of `load_model` so stale cancels don't abort a fresh load). `_cancel_ai` handles a running loader, the AI menu shows "Cancel AI" during loads, Esc cancels it too, and `LoadWorker` emits a new `cancelled` signal that resets the UI to idle. Verified headless: cancelling mid-download aborts before the next file.*

- **E5** ⚪ **RAG context budget is character-based (`budget=12000`), not token-based, and can silently exceed the model's real `N_CTX=8192` token window** for token-dense content (tables, code, non-Latin text). — ✅ **RESOLVED**
  *Fixed: `assemble_context` now takes a token budget (`CONTEXT_TOKEN_BUDGET = 6000`, safely inside N_CTX minus MAX_TOKENS), estimating tokens as `chars/4` and capping each chunk. Verified headless: a 13.5k-char assembly lands at ~3.4k estimated tokens, well under the budget.*

- **E6** ⚪ **A cancelled AI run still reports "finished_ok" with no distinction from a completed run** — the truncated output is saved to notes and shown identically to a full answer, no "cancelled — may be incomplete" marker. — ✅ **RESOLVED**
  *Fixed: `InferWorker` emits a new `cancelled(heading)` signal when `ai.cancelled` is set after `generate` returns (instead of `finished_ok`); `MainWindow` ends the stream and appends a `> ✂️ Cancelled — answer may be incomplete` marker to the notes. Verified headless: a cancelled run emits `cancelled`, never `finished_ok`.*

---

## Epic F — Core PDF reader: crash safety & navigation
- **F1** 🔴 **Whole app hard-crashes (SIGABRT) if `Ctrl+0` is pressed twice before opening any PDF.** `_apply_zoom()` indexes `self.engine.page_sizes[0][0]` unconditionally; with no PDF loaded that list is empty. Reproduced live: two genuine `Ctrl+0` key events → `IndexError` → process exit code 134. — ✅ **RESOLVED** — `_apply_zoom()` early-returns when `not self.engine.doc or not self.engine.page_sizes or not self.pages`. Verified headless.

- **F2** 🔴 **No global exception handler anywhere — any uncaught exception in a Qt slot kills the entire process instantly, discarding unsaved notes.** Only 3 real `except` blocks exist in all of `main.py`'s 1128 lines; there is no `sys.excepthook` and no wrapper around `app.exec()`. F1 above is a live demonstration of exactly this. — ✅ **RESOLVED** — `_install_excephook()` installs a `sys.excepthook` (logs to `ai.log`, shows a contained dialog on the main thread); exceptions on worker threads are logged only. Verified: a raised exception in a `QTimer` slot is contained and the app continues (exit 0).

- **F3** 🟠 **Keyboard scrolling (arrow keys, PageUp/PageDown, Home/End) doesn't work anywhere in the document view.** — ✅ **RESOLVED**
  `PageView` never calls `setFocus()` on click, and `MainWindow.keyPressEvent` has no handling for these keys — the scroll area's own built-in key handling is fully functional but unreachable because nothing ever routes focus to it. Reproduced live (manually focusing the scroll area proves the underlying scroll logic works fine).
  *Fixed: `PageView` is now `StrongFocus` and calls `setFocus()` on mouse-press, so key events propagate to `MainWindow`, which routes arrows/PageUp/Home/End to the document scroll bar via `_scroll_document()`. Verified headless (arrow/page/Home/End move the scrollbar).*

- **F4** 🟠 **Fit-to-width zoom is computed only from page 0's width and applied uniformly** — a document with mixed page sizes renders every other page at the wrong on-screen width. Reproduced with a 4-page test PDF containing one landscape page: it rendered at exactly 2× the correct width. — ✅ **RESOLVED**
  *Fixed: `_apply_zoom` gives each page its own fit-to-width zoom (`avail / page_width`), so a landscape page renders at its correct width while portrait pages keep theirs. Verified headless: portrait and landscape pages report different zooms in fit-width mode.*

- **F5** 🟠 **Zoom/resize eagerly re-renders every page in the document (ignoring viewport visibility) and fully clears the LRU render cache every time**, including on every `resizeEvent` fired continuously during a live window-resize drag while fit-to-width is on. Reproduced with a 60-page test PDF: a single resize event triggered 60 full re-renders. On larger documents (`MAX_CACHE=50`) this can visibly freeze the UI. — ✅ **RESOLVED**
  *Fixed: `_apply_zoom` no longer flushes the LRU cache (it was clearing every render key for no reason — width-keyed entries evict naturally). A `render_visible_only` pass renders just the pages in/near the viewport, scrolling re-renders newly-visible pages on demand, and `resizeEvent` debounces a full re-render 200 ms after the drag settles. Verified headless: a viewport-aware zoom pass renders only the visible pages.*

- **F6** 🟡 **Search finds the right pages but never highlights the matched text on-page**, and folds multiple in-page hits into a single result in the "1/N" counter. — ✅ **RESOLVED**
  *Fixed: `engine.search` uses `page.search_for` and returns one `(page_idx, bbox)` per real hit; the "1/N" counter reflects total hits; matches are highlighted in orange on every page via `PageView.set_search_hits`; navigating a hit scrolls it into the viewport; `clear_search` removes the overlays. Verified headless: a 2-hit landscape page yields two results and two highlights.*

- **F7** ⚪ **Latent bug: `render_page`'s non-RGB(A) pixmap branch would mis-decode the image buffer** (assumes `Format_RGBA8888` regardless of actual channel count) — currently unreachable since the app always requests RGB, but should convert/branch explicitly rather than silently mismatch format-to-buffer if that ever changes. — ✅ **RESOLVED**
  *Fixed: `render_page` requests `colorspace=fitz.csRGB` explicitly and converts any remaining non-RGB(A) pixmap via `fitz.Pixmap(fitz.csRGB, pix)` before choosing `RGB888`/`RGBA8888` to match the buffer. Verified headless: rendered pages are valid RGB(A) QImages.*

---

## Epic G — Storage & data safety
- **G1** 🟠 **Opening a PDF when the data directory isn't writable crashes the whole app** — `load_pdf()`'s try/except only wraps `PdfEngine.open()`; the next line, `PdfStorage(path)` (which does an unguarded `mkdir`), is outside it. Reproduced: a read-only data directory raises an uncaught `PermissionError`. Combined with F2 (no global handler), this SIGABRTs the process. — ✅ **RESOLVED** — `PdfStorage(path)` (and notes load) moved inside `load_pdf`'s try/except; failures surface as a `QMessageBox` instead of a crash.

- **G2** 🟠 **Filename sanitization collides distinct documents into one notes folder, leaking one PDF's notes/highlights into another's.** — ✅ **RESOLVED**
  `_safe_name()` maps every non-alphanumeric character to `_` with no collision check — reproduced directly: `"a b.pdf"` and `"a_b.pdf"` both sanitize to the identical folder name.
  *Fixed: each notes folder records its owning file in `annotations.json["pdf_name"]`; `PdfStorage._resolve_folder()` reuses an existing folder only when its owner matches, otherwise picks a deterministic `-<crc16>` suffix. Reopening a PDF still reuses the same folder. Verified headless: `a b.pdf` → `a_b`, `a_b.pdf` → `a_b-d65d`, both reopen stably.*

- **G3** 🟠 **No locking on `notes.md`/`annotations.json` — opening the same PDF twice (or two instances) causes a silent lost-update race.** Both files are loaded once into memory and every save blindly overwrites the whole file from that stale in-memory snapshot, with no re-read-and-merge. — ✅ **RESOLVED**
  *Fixed: `_save_json` now runs under a cross-process lock (`fcntl.flock` / `msvcrt`) on `notes/<pdf>/.lock` and *re-reads the disk state and merges* before overwriting — `image_descriptions` unions per-key, `narration_position` keeps the newest timestamp, and `highlights`/`captures` union by stable identity, so one instance's save never clobbers another's additions. `save_notes` writes under the same lock. Verified headless: two "instances" saving concurrently preserve both image-description entries.*

- **G4** 🟠 **`notes.md`/`annotations.json` are written non-atomically** (`Path.write_text()` truncates immediately, no temp-file+rename) — a crash or kill mid-save can destroy the file rather than just losing the latest edit. — ✅ **RESOLVED**
  *Fixed: `storage.save_notes()` already wrote `notes.md` atomically (temp file + `fsync` + `os.replace`); `_save_json()` now does the same for `annotations.json`, so all per-PDF state writes are atomic. Verified headless: writes produce valid JSON with no stray `.tmp` files.*

- **G5** 🟡 **Password-protected PDFs are unconditionally rejected with no password-entry UI** — the failure is caught gracefully (no crash), but there's no retry-with-password path. — ✅ **RESOLVED**
  *Fixed: `PdfEngine.open` authenticates a supplied password and raises a dedicated `PasswordRequired` when the file is encrypted and no valid password was given. `MainWindow.load_pdf` loops on that exception: it prompts via `QInputDialog` (password echo), rejects wrong passwords with a warning and a retry, and gives up cleanly if the user cancels. Verified headless: no password → `PasswordRequired`; wrong password → `PasswordRequired`; correct password → document decrypts (`is_encrypted` False) and renders.*

---

## Epic H — Product & hackathon-demo polish
- **H1** 🟠 **README's accessibility shortcut table is missing two real, working shortcuts** (`C` — continue reading cross-session, `?` — accessibility help) that exist in code and in `AGENTS.md`. A judge reading only the public README would miss the "resume where I left off" feature entirely. — ✅ **RESOLVED** — README and `docs/accessibility.md` now list `C` and `?` (plus `Ctrl+Shift+A`).
- **H2** 🟡 **No visible progress indicator for either first-run download** (multi-GB AI model, ~65MB voice) beyond status-bar text; the voice download additionally blocks the UI thread entirely (see **A9**). — ✅ **RESOLVED**
  *Fixed: the AI model download already drives the toolbar `QProgressBar` with real byte progress; the voice download (already off-thread since A9) now shows an indeterminate busy `QProgressBar` in the status bar while `VoiceLoadWorker` runs, hidden on ready/failure. Verified headless: the status-bar widget is wired and hidden at rest.*

---

## Investigated, not confirmed
- **"Closing the app while an AI model is still loading crashes with SIGABRT."** The underlying design gap is real (no cooperative cancellation in the model loader; `closeEvent` doesn't confirm actual thread termination before unloading) and is worth keeping in mind, but three independent, faithful reproduction attempts — including driving the real `MainWindow.closeEvent()` against a real in-flight `LoadWorker` — never produced a crash. Not filed as a ticket; flagging here so it isn't rediscovered and re-litigated without cause.
