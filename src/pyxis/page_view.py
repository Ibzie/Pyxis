from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QLabel


class PageView(QLabel):
    rightClicked = pyqtSignal(int, QPoint, QPointF)
    captureDone = pyqtSignal(int)
    describeImageRequested = pyqtSignal(int, tuple)   # (page_idx, bbox)

    def __init__(self, page_idx, width_pt, height_pt, parent=None):
        super().__init__(parent)
        self.page_idx = page_idx
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.zoom = 1.0
        self.chars = []
        self.highlights = []
        self.selection = []
        self.drag_start = None
        self.drag_current = None
        self.capture_mode = False
        self.capture_rect = None
        self.image_blocks = []        # list of (x0, y0, x1, y1) tuples
        self._image_focus = None      # index into image_blocks being described
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #1e1e1e;")

    def set_image(self, img):
        self.setPixmap(QPixmap.fromImage(img))

    def set_zoom(self, zoom):
        self.zoom = zoom
        self.setFixedSize(int(self.width_pt * zoom), int(self.height_pt * zoom))

    def set_chars(self, chars):
        self.chars = chars

    def set_highlights(self, highlights):
        self.highlights = highlights
        self.update()

    def set_image_blocks(self, blocks):
        """Set the list of image-region bboxes (x0, y0, x1, y1) for this page."""
        self.image_blocks = list(blocks)
        self._image_focus = None
        self.update()

    def next_image(self):
        """Return the bbox of the next image block, or None if none left."""
        if not self.image_blocks:
            return None
        start = (self._image_focus + 1) if self._image_focus is not None else 0
        for i in range(start, len(self.image_blocks)):
            self._image_focus = i
            self.update()
            return self.image_blocks[i]
        return None

    def set_image_focus(self, idx):
        self._image_focus = idx
        self.update()

    def image_at(self, pos):
        """Return (index, bbox) of the image under the cursor, or (None, None)."""
        x, y = pos.x() / self.zoom, pos.y() / self.zoom
        for i, bbox in enumerate(self.image_blocks):
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return i, bbox
        return None, None

    def clear_selection(self):
        self.selection = []
        self.capture_rect = None
        self.update()

    def set_capture_mode(self, enabled):
        self.capture_mode = enabled
        if not enabled:
            self.capture_rect = None
            self.update()

    def get_selection_text(self):
        if not self.selection:
            return ""
        chars = sorted(self.selection, key=lambda c: (c[2], c[1]))
        lines = []
        line = []
        last_y = None
        last_x_end = None
        for ch, x0, y0, x1, y1 in chars:
            if last_y is None or abs(y0 - last_y) > 5:
                if line:
                    lines.append("".join(line))
                line = [ch]
                last_y = y0
                last_x_end = x1
            else:
                if x0 - last_x_end > 8:
                    line.append(" ")
                line.append(ch)
                last_x_end = x1
        if line:
            lines.append("".join(line))
        return "\n".join(lines)

    def get_selection_bbox(self):
        if not self.selection:
            return None
        return (
            min(c[1] for c in self.selection),
            min(c[2] for c in self.selection),
            max(c[3] for c in self.selection),
            max(c[4] for c in self.selection),
        )

    def get_capture_rect(self):
        return self.capture_rect

    def highlight_at(self, pos: QPoint):
        x, y = pos.x() / self.zoom, pos.y() / self.zoom
        for i, hl in enumerate(self.highlights):
            if hl[0] <= x <= hl[2] and hl[1] <= y <= hl[3]:
                return i
        return None

    def _pdf_to_screen(self, x0, y0, x1, y1):
        return QRect(int(x0 * self.zoom), int(y0 * self.zoom),
                     int((x1 - x0) * self.zoom), int((y1 - y0) * self.zoom))

    def _screen_to_pdf(self, pos: QPoint):
        return QPointF(pos.x() / self.zoom, pos.y() / self.zoom)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 235, 59, 80))
        for hl in self.highlights:
            p.drawRect(self._pdf_to_screen(*hl))
        if self.selection:
            p.setBrush(QColor(33, 150, 243, 80))
            for c in self.selection:
                p.drawRect(self._pdf_to_screen(c[1], c[2], c[3], c[4]))
        if self.capture_rect:
            p.setPen(QPen(QColor(255, 87, 34), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.capture_rect)
        if self.image_blocks and self._image_focus is not None:
            p.setPen(QPen(QColor(255, 215, 0), 2, Qt.PenStyle.SolidLine))
            p.setBrush(QColor(255, 215, 0, 30))
            idx = self._image_focus
            if 0 <= idx < len(self.image_blocks):
                p.drawRect(self._pdf_to_screen(*self.image_blocks[idx]))

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.drag_start = self._screen_to_pdf(ev.pos())
            self.drag_current = self.drag_start
            if not self.capture_mode:
                self.selection = []
            else:
                self.capture_rect = None
            self.update()
        elif ev.button() == Qt.MouseButton.RightButton:
            pdf_pos = self._screen_to_pdf(ev.pos())
            idx, bbox = self.image_at(ev.pos())
            if bbox:
                self._image_focus = idx
                self.update()
                self.describeImageRequested.emit(self.page_idx, bbox)
            self.rightClicked.emit(self.page_idx, self.mapToGlobal(ev.pos()), pdf_pos)

    def mouseMoveEvent(self, ev: QMouseEvent):
        if ev.buttons() == Qt.MouseButton.LeftButton and self.drag_start:
            self.drag_current = self._screen_to_pdf(ev.pos())
            self._update_region()
            self.update()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton and self.drag_start:
            self.drag_current = self._screen_to_pdf(ev.pos())
            self._update_region()
            self.drag_start = None
            self.drag_current = None
            if self.capture_mode and self.capture_rect and self.capture_rect.width() >= 10 and self.capture_rect.height() >= 10:
                self.captureDone.emit(self.page_idx)

    def _update_region(self):
        if self.capture_mode:
            p0 = QPointF(self.drag_start.x() * self.zoom, self.drag_start.y() * self.zoom)
            p1 = QPointF(self.drag_current.x() * self.zoom, self.drag_current.y() * self.zoom)
            x, y = min(p0.x(), p1.x()), min(p0.y(), p1.y())
            w, h = abs(p1.x() - p0.x()), abs(p1.y() - p0.y())
            self.capture_rect = QRect(int(x), int(y), int(w), int(h))
        else:
            x0, y0 = self.drag_start.x(), self.drag_start.y()
            x1, y1 = self.drag_current.x(), self.drag_current.y()
            left, right = min(x0, x1), max(x0, x1)
            top, bottom = min(y0, y1), max(y0, y1)
            self.selection = [c for c in self.chars
                              if c[1] < right and c[3] > left and c[2] < bottom and c[4] > top]
