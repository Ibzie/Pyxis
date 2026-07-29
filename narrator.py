"""Narrator orchestrator — walks RAG chunks for a page, enqueues text to the
SpeechQueue, and describes images via the AI vision model.

The worker runs on a QThread so the UI never blocks. Text chunks are
enqueued immediately (the SpeechQueue runs on its own thread and will
speak them while the narrator moves on). Image chunks trigger a vision
model call (~20 s on Gemma 4 E4B) — the caption is appended to notes
and enqueued for speech when ready. Cached descriptions (from
`storage.get_image_description`) skip the model entirely.
"""

import logging
import fitz
from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("narrator")


class NarratorWorker(QThread):
    """Read a page aloud: text chunks → TTS, image chunks → vision model → TTS.

    Signals:
        page_started(int)               — page narration began
        chunk_queued(str)               — a text chunk was enqueued to TTS
        chunk_progress(int, int)        — (page_idx, chunk_index) before each chunk
        caption_ready(str, str)         — (description, image_md) ready for notes
        page_done(int)                  — all chunks processed (speech may still play)
        failed(str)                     — error
    """

    page_started = pyqtSignal(int)
    chunk_queued = pyqtSignal(str)
    chunk_progress = pyqtSignal(int, int)
    caption_ready = pyqtSignal(str, str)
    page_done = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, engine, rag, ai, storage, speech_queue, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.rag = rag
        self.ai = ai
        self.storage = storage
        self.speech = speech_queue
        self._page_idx = None
        self._start_chunk = 0
        self._running = True

    def read_page(self, page_idx, start_chunk=0):
        """Queue a page for narration, optionally skipping the first
        `start_chunk` chunks (used by the cross-session resume command)."""
        self._page_idx = page_idx
        self._start_chunk = start_chunk
        if not self.isRunning():
            self.start()

    def cancel(self):
        self._running = False
        self.speech.cancel()

    def run(self):
        if self._page_idx is None:
            return
        idx = self._page_idx
        start = self._start_chunk
        self._page_idx = None
        self._start_chunk = 0
        try:
            self._narrate_page(idx, start)
        except Exception as e:
            log.exception("narrator error on page %d", idx)
            self.failed.emit(str(e))

    def _narrate_page(self, page_idx, start_chunk=0):
        self.page_started.emit(page_idx)
        log.info("narrating page %d (from chunk %d)", page_idx, start_chunk)

        # Gather chunks for this page in source order.
        chunks = [c for c in self.rag.chunks if c["page"] == page_idx]
        if start_chunk > 0 and chunks:
            chunks = chunks[start_chunk:]
        if not chunks:
            # No RAG chunks (or we skipped them all) — read raw page text as
            # fallback, but only when starting from the top.
            if start_chunk == 0:
                doc = fitz.open(self.engine.path)
                text = doc.load_page(page_idx).get_text()
                doc.close()
                if text.strip():
                    self.chunk_progress.emit(page_idx, 0)
                    self.speech.enqueue(text)
                    self.chunk_queued.emit(text[:80])
        else:
            doc = fitz.open(self.engine.path)
            for i, c in enumerate(chunks):
                if not self._running:
                    break
                # Absolute chunk index (relative to the page's full chunk list)
                # so the UI can persist a stable resume point.
                abs_idx = start_chunk + i
                self.chunk_progress.emit(page_idx, abs_idx)
                if c["type"] == "image":
                    self._describe_and_enqueue(doc, page_idx, c)
                else:
                    text = c["text"]
                    self.speech.enqueue(text)
                    self.chunk_queued.emit(text[:80])
            doc.close()

        self.page_done.emit(page_idx)

    def _describe_and_enqueue(self, doc, page_idx, chunk):
        """Describe an image chunk: check cache, else call vision model."""
        bbox = chunk.get("image_rect")
        if not bbox:
            return

        # Check cache first — skip the model if we've described this before.
        cached = self.storage.get_image_description(page_idx, bbox)
        if cached:
            desc = cached["description"]
            log.info("using cached image description for page %d", page_idx)
            self._emit_caption(page_idx, desc, cached.get("file", ""))
            self.speech.enqueue(f"Image on page {page_idx + 1}. {desc}")
            return

        # Extract the image region as PNG bytes.
        try:
            page = doc.load_page(page_idx)
            rect = fitz.Rect(*bbox)
            # 2x zoom for better vision model accuracy.
            pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes("png")
        except Exception as e:
            log.warning("image extraction failed (page %d): %s", page_idx, e)
            return

        # Call the vision model.
        if not self.ai.is_multimodal():
            desc = "Image present but vision model not loaded."
        else:
            try:
                desc = self.ai.describe_image(png_bytes)
            except Exception as e:
                log.warning("describe_image failed: %s", e)
                desc = f"Image description unavailable: {e}"

        # Save the image PNG and cache the description.
        img_path = self.storage.save_rag_image(
            page_idx, fitz.Pixmap(pix)) if pix else None
        self.storage.save_image_description(page_idx, bbox, desc, img_path)

        self._emit_caption(page_idx, desc,
                           str(img_path.relative_to(self.storage.folder))
                           if img_path else "")
        self.speech.enqueue(f"Image on page {page_idx + 1}. {desc}")

    def _emit_caption(self, page_idx, desc, rel_path):
        """Build markdown for the caption and emit it for notes panel."""
        md = f"\n\n#### 📷 Page {page_idx + 1} Figure\n\n{desc}\n"
        if rel_path:
            md += f"\n![caption]({rel_path})\n"
        self.caption_ready.emit(desc, md)
