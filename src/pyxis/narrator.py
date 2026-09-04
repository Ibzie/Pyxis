"""Narration renderer — walks a page's RAG chunks, synthesizes text to PCM
and describes images via the AI vision model (E9 render-then-play).

The worker runs on a persistent QThread, pulling jobs from a small queue:
`read_page` jobs narrate a document page (optionally from a saved chunk
offset), `read_text` jobs speak ad-hoc text (greetings, help, notes).
Each sentence is synthesized via the TTS engine's `render_pcm` and emitted
as `chunk_ready` — the NarrationPlayer appends it to its timeline and
plays while rendering continues. Image chunks trigger a vision model call
(~20 s on Gemma 4 E4B); the caption is appended to notes via
`caption_ready` and rendered like any other text. Cached descriptions
(from `storage.get_image_description`) skip the model entirely.
`flush_jobs` aborts the in-flight render so a new R/C/N command starts
clean instead of queueing behind stale audio.
"""

import time
import logging
import threading
import fitz
from PyQt6.QtCore import QThread, pyqtSignal

from .speech import split_sentences

log = logging.getLogger("narrator")


class NarratorWorker(QThread):
    """Render a page (or plain text) to PCM chunks for the NarrationPlayer.

    Signals:
        page_started(int)                  — page rendering began
        chunk_ready(object, object, int, int) — (samples, page|None, chunk, sr)
        caption_ready(str, str)            — (description, image_md) for notes
        render_status(str)                 — human-readable progress
        page_done(int)                     — all chunks of a page rendered
        render_done()                      — a job finished cleanly (the player
                                             may now run out and finish)
        failed(str)                        — error
    """

    page_started = pyqtSignal(int)
    # `page` must be object-typed: text jobs pass None, and PyQt marshals
    # None through an int parameter as garbage (it then lands in the
    # persisted narration position — E11).
    chunk_ready = pyqtSignal(object, object, int, int)
    caption_ready = pyqtSignal(str, str)
    render_status = pyqtSignal(str)
    page_done = pyqtSignal(int)
    render_done = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, engine, rag, ai, storage, speech_engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.rag = rag
        self.ai = ai
        self.storage = storage
        self.speech = speech_engine
        self._jobs = []
        self._job_lock = threading.Lock()
        self._running = True
        self._flush = False
        self._describing = False

    # ── main-thread API ────────────────────────────────────────────────────
    def read_page(self, page_idx, start_chunk=0):
        """Queue a page for narration, optionally skipping the first
        `start_chunk` chunks (cross-session resume)."""
        with self._job_lock:
            self._jobs.append(("page", page_idx, start_chunk))
        if not self.isRunning():
            self.start()

    def read_text(self, text):
        """Queue plain text for narration (greetings, help, notes)."""
        with self._job_lock:
            self._jobs.append(("text", text))
        if not self.isRunning():
            self.start()

    def flush_jobs(self):
        """Abort the current render and drop pending jobs — the next
        R/C/N command starts clean instead of queueing behind stale audio."""
        with self._job_lock:
            self._jobs.clear()
            self._flush = True

    def stop(self):
        with self._job_lock:
            self._jobs.clear()
        self._running = False
        self._flush = True
        self.wait(3000)

    def is_describing(self):
        """True while a vision call is in flight — the UI refuses model
        switches during it (freeing the model under inference crashes)."""
        return self._describing

    def set_rag(self, rag):
        """Point at the (possibly freshly built) retrieval index."""
        self.rag = rag

    def set_storage(self, storage):
        """Point at the currently open PDF's storage folder."""
        self.storage = storage

    # ── render loop ─────────────────────────────────────────────────────────
    def run(self):
        while self._running:
            with self._job_lock:
                self._flush = False
                job = self._jobs.pop(0) if self._jobs else None
            if job is None:
                time.sleep(0.1)
                continue
            try:
                self._render_job(job)
                if not self._aborted():
                    # Clean end of a job — the player may now run out. Not
                    # emitted on aborts: a flush means a new session is
                    # already queued behind us.
                    self.render_done.emit()
            except Exception as e:
                log.exception("narrator error")
                self.failed.emit(str(e))

    def _aborted(self):
        return (not self._running) or self._flush

    def _render_job(self, job):
        if job[0] == "text":
            self._emit_text(job[1], None, -1)
            return
        _, page_idx, start_chunk = job
        self.page_started.emit(page_idx)
        self.render_status.emit(f"Rendering page {page_idx + 1}…")

        # Gather chunks for this page in source order. `rag` may be None (A8:
        # narration must work before the index is built / model is loaded).
        chunks = [c for c in self.rag.chunks if c["page"] == page_idx] \
            if self.rag is not None else []
        if start_chunk > 0 and chunks:
            chunks = chunks[start_chunk:]
        if not chunks:
            # No RAG chunks (or none available) — read raw page text as
            # fallback. Without an index we can't honor start_chunk, so a
            # "continue" with no RAG falls back to the top of the page.
            if start_chunk == 0 or self.rag is None:
                doc = fitz.open(self.engine.path)
                try:
                    text = doc.load_page(page_idx).get_text()
                finally:
                    doc.close()
                if text.strip():
                    self._emit_text(text, page_idx, 0)
        else:
            doc = fitz.open(self.engine.path)
            try:
                for i, c in enumerate(chunks):
                    if self._aborted():
                        return
                    # Absolute chunk index (relative to the page's full chunk
                    # list) so the player persists a stable resume point.
                    abs_idx = start_chunk + i
                    if c["type"] == "image":
                        text = self._describe(doc, page_idx, c)
                    else:
                        text = c["text"]
                    if text:
                        self._emit_text(text, page_idx, abs_idx)
            finally:
                doc.close()
        if not self._aborted():
            self.page_done.emit(page_idx)

    def _emit_text(self, text, page, chunk):
        for piece in split_sentences(text):
            if self._aborted():
                return
            rendered = self.speech.render_pcm(piece)
            if rendered is None:
                continue
            samples, sr = rendered
            self.chunk_ready.emit(samples, page, chunk, sr)

    def _describe(self, doc, page_idx, chunk):
        """Describe an image chunk: check cache, else call vision model.
        Returns the text to narrate ("" if the chunk was unusable)."""
        bbox = chunk.get("image_rect")
        if not bbox:
            return ""

        # Check cache first — skip the model if we've described this before.
        cached = self.storage.get_image_description(page_idx, bbox)
        if cached:
            desc = cached["description"]
            log.info("using cached image description for page %d", page_idx)
            self._emit_caption(page_idx, desc, cached.get("file", ""))
            return f"Image on page {page_idx + 1}. {desc}"

        # Extract the image region as PNG bytes.
        try:
            page = doc.load_page(page_idx)
            rect = fitz.Rect(*bbox)
            # 2x zoom for better vision model accuracy.
            pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes("png")
        except Exception as e:
            log.warning("image extraction failed (page %d): %s", page_idx, e)
            return ""

        # Call the vision model. `ai` may be unloaded (A8) — degrade to a
        # placeholder caption instead of failing the whole narration.
        if not self.ai.is_multimodal():
            desc = "Image present but vision model not loaded."
        else:
            self.render_status.emit(f"Describing an image on page {page_idx + 1}…")
            self._describing = True
            try:
                desc = self.ai.describe_image(png_bytes)
            except Exception as e:
                log.warning("describe_image failed: %s", e)
                desc = f"Image description unavailable: {e}"
            finally:
                self._describing = False

        # Save the image PNG and cache the description.
        img_path = self.storage.save_rag_image(
            page_idx, fitz.Pixmap(pix)) if pix else None
        self.storage.save_image_description(page_idx, bbox, desc, img_path)

        self._emit_caption(page_idx, desc,
                           str(img_path.relative_to(self.storage.folder))
                           if img_path else "")
        return f"Image on page {page_idx + 1}. {desc}"

    def _emit_caption(self, page_idx, desc, rel_path):
        """Build markdown for the caption and emit it for notes panel."""
        md = f"\n\n#### 📷 Page {page_idx + 1} Figure\n\n{desc}\n"
        if rel_path:
            md += f"\n![caption]({rel_path})\n"
        self.caption_ready.emit(desc, md)
