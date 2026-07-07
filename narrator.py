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
        caption_ready(str, str)         — (description, image_md) ready for notes
        page_done(int)                  — all chunks processed (speech may still play)
        failed(str)                     — error
    """

    page_started = pyqtSignal(int)
    chunk_queued = pyqtSignal(str)
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
        self._running = True

    def read_page(self, page_idx):
        """Queue a page for narration. Call from the UI thread."""
        self._page_idx = page_idx
        if not self.isRunning():
            self.start()

    def cancel(self):
        self._running = False
        self.speech.cancel()

    def run(self):
        if self._page_idx is None:
            return
        idx = self._page_idx
        self._page_idx = None
        try:
            self._narrate_page(idx)
        except Exception as e:
            log.exception("narrator error on page %d", idx)
            self.failed.emit(str(e))

    def _narrate_page(self, page_idx):
        self.page_started.emit(page_idx)
        log.info("narrating page %d", page_idx)

        # Gather chunks for this page in source order.
        chunks = [c for c in self.rag.chunks if c["page"] == page_idx]
        if not chunks:
            # No RAG chunks — read raw page text as fallback.
            doc = fitz.open(self.engine.path)
            text = doc.load_page(page_idx).get_text()
            doc.close()
            if text.strip():
                self.speech.enqueue(text)
                self.chunk_queued.emit(text[:80])
        else:
            doc = fitz.open(self.engine.path)
            for c in chunks:
                if not self._running:
                    break
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
