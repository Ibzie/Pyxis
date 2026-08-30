from PyQt6.QtCore import QThread, pyqtSignal
from .ai_layer import AILayer


class LoadWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, ai, parent=None, tier_idx=None):
        super().__init__(parent)
        self.ai = ai
        self.repo_id = None
        self.filename = None
        self.tier_idx = tier_idx

    def run(self):
        try:
            self.ai.load_model(
                on_status=lambda m: self.status.emit(m),
                on_progress=lambda d, t, l: self.progress.emit(int(d), int(t), l),
                repo_id=self.repo_id, filename=self.filename,
                tier_idx=self.tier_idx,
            )
            self.done.emit(self.ai.model_label())
        except Exception as e:
            if self.ai.cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(str(e))


class IndexWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(object)     # RagIndex
    failed = pyqtSignal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        try:
            import fitz
            from .rag import RagIndex
            doc = fitz.open(self.engine.path)
            rag = RagIndex()
            total = doc.page_count
            for i in range(total):
                self.progress.emit(i, total, f"Indexing page {i+1}/{total}…")
                rag.index_page(doc.load_page(i), i)
            rag.finalize()
            doc.close()
            self.done.emit(rag)
        except Exception as e:
            self.failed.emit(str(e))


class InferWorker(QThread):
    token = pyqtSignal(str)
    heading = pyqtSignal(str)
    image_request = pyqtSignal(list)   # list of image chunk dicts
    finished_ok = pyqtSignal(str)
    cancelled = pyqtSignal(str)        # heading (truncated run, E6)
    failed = pyqtSignal(str)

    def __init__(self, ai, command, parent=None, **kwargs):
        super().__init__(parent)
        self.ai = ai
        self.command = command
        self.kwargs = kwargs

    def run(self):
        try:
            rag = self.kwargs.pop("rag", None)
            doc_title = self.kwargs.pop("doc_title", "")
            if self.command == "answer_rag" and rag and rag.is_ready:
                expanded = self.ai.expand_query(self.kwargs.get("question", ""), doc_title)
                chunks = rag.retrieve(expanded)
                ctx, images = rag.assemble_context(chunks)
                self.kwargs["context"] = ctx
                if images:
                    self.image_request.emit(images)
            messages, heading = self.ai.build_request(self.command, **self.kwargs)
            self.heading.emit(heading)
            self.ai.generate(messages, on_token=lambda t: self.token.emit(t))
            if self.ai.cancelled:
                # E6: a cancelled run is NOT a successful one — the stream was
                # truncated mid-token, so it must be surfaced distinctly.
                self.cancelled.emit(heading)
            else:
                self.finished_ok.emit(heading)
        except Exception as e:
            self.failed.emit(str(e))