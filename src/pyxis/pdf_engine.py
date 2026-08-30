import fitz
from collections import OrderedDict
from PyQt6.QtGui import QImage

ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
MAX_CACHE = 50


class PasswordRequired(Exception):
    """Raised by PdfEngine.open when a PDF is encrypted and no valid
    password was supplied (G5) — the UI prompts and retries."""


class PdfEngine:
    def __init__(self):
        self.doc = None
        self.path = ""
        self.page_count = 0
        self.metadata = {}
        self.version = ""
        self.bookmarks = []
        self.cache = OrderedDict()
        self.page_sizes = []

    def open(self, path, password=None):
        self.close()
        doc = fitz.open(path)
        if doc.needs_pass:
            if password and doc.authenticate(password):
                pass
            else:
                doc.close()
                raise PasswordRequired(path)
        self.doc = doc
        self.path = path
        self.page_count = len(self.doc)
        self.metadata = self.doc.metadata or {}
        self.version = self.metadata.get("format", "PDF")
        self.bookmarks = []
        self.cache.clear()
        self.page_sizes = []
        for i in range(self.page_count):
            page = self.doc.load_page(i)
            rect = page.rect
            self.page_sizes.append((rect.width, rect.height))
        try:
            if self.doc.outline:
                self._read_bookmarks(self.doc.outline, 0)
        except Exception:
            self.bookmarks = []

    def close(self):
        if self.doc:
            self.doc.close()
        self.doc = None
        self.path = ""
        self.page_count = 0
        self.metadata = {}
        self.version = ""
        self.bookmarks = []
        self.cache.clear()
        self.page_sizes = []

    def _read_bookmarks(self, item, level):
        while item:
            try:
                title = item.title
            except Exception:
                title = ""
            self.bookmarks.append({"title": title, "page": item.page, "level": level})
            if item.down:
                self._read_bookmarks(item.down, level + 1)
            item = item.next

    def page_size(self, idx, zoom=1.0):
        w, h = self.page_sizes[idx]
        return w * zoom, h * zoom

    def render_page(self, idx, target_width):
        key = (idx, int(target_width))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        page = self.doc.load_page(idx)
        zoom = target_width / self.page_sizes[idx][0]
        mat = fitz.Matrix(zoom, zoom)
        # Force an RGB(A) colorspace so `pix.n` always matches the QImage
        # buffer format (F7) — a grayscale page would otherwise be mis-decode
        # as RGBA8888 and show garbage.
        pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
        if pix.n not in (3, 4):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        fmt = QImage.Format.Format_RGBA8888 if pix.n == 4 else QImage.Format.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
        self.cache[key] = img
        if len(self.cache) > MAX_CACHE:
            self.cache.popitem(last=False)
        return img

    def invalidate_cache(self):
        self.cache.clear()

    def extract_page_text(self, idx):
        if not self.doc:
            return ""
        return self.doc.load_page(idx).get_text()

    def get_text_chars(self, idx):
        if not self.doc:
            return []
        chars = []
        page = self.doc.load_page(idx)
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for c in span.get("chars", []):
                        r = c["bbox"]
                        chars.append((c["c"], r[0], r[1], r[2], r[3]))
        return chars

    def search(self, query):
        """Return every match as (page_idx, bbox) where bbox is
        (x0, y0, x1, y1) in PDF points — one entry per in-page hit so the
        "1/N" counter reflects real matches and pages can be highlighted."""
        if not query or not self.doc:
            return []
        hits = []
        for i in range(self.page_count):
            page = self.doc.load_page(i)
            for r in page.search_for(query):
                hits.append((i, (r.x0, r.y0, r.x1, r.y1)))
        return hits
