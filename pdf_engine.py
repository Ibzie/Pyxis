import fitz
from collections import OrderedDict
from PyQt6.QtGui import QImage

ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
MAX_CACHE = 50


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

    def open(self, path):
        self.close()
        self.doc = fitz.open(path)
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
        pix = page.get_pixmap(matrix=mat, alpha=False)
        if pix.n == 4:
            fmt = QImage.Format.Format_RGBA8888
        elif pix.n == 3:
            fmt = QImage.Format.Format_RGB888
        else:
            fmt = QImage.Format.Format_RGBA8888
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
        if not query or not self.doc:
            return []
        q = query.lower()
        found = []
        for i in range(self.page_count):
            text = self.extract_page_text(i).lower()
            if q in text:
                found.append(i)
        return found
