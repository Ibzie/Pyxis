"""Freehand drawing canvas for the Whiteboard tab (D1).

A plain QWidget + QPainter drawing on a QPixmap buffer — the same style the
rest of the app uses (page_view.py). Strokes are flattened straight onto the
buffer and persisted as a single PNG per PDF (`notes/<pdf>/whiteboard.png`),
matching the highlights/captures convention rather than storing a stroke log.
"""

from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton


class _Canvas(QWidget):
    """The drawable surface: strokes land on a QPixmap buffer."""

    def __init__(self, wb, parent=None):
        super().__init__(parent)
        self.wb = wb
        self._buffer = None
        self.setStyleSheet("background-color: #1e1e1e;")

    def _ensure_buffer(self):
        if self._buffer is None:
            w, h = max(1, self.width()), max(1, self.height())
            self._buffer = QPixmap(w, h)
            self._buffer.fill(QColor("#1e1e1e"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # M6: the buffer is allocated at first stroke; a window resize after
        # that left a dead zone where new strokes were silently dropped.
        # Grow (never shrink) the buffer, preserving what's already drawn.
        if self._buffer is not None and (
                self._buffer.width() < self.width()
                or self._buffer.height() < self.height()):
            new = QPixmap(max(1, self.width()), max(1, self.height()))
            new.fill(QColor("#1e1e1e"))
            p = QPainter(new)
            p.drawPixmap(0, 0, self._buffer)
            p.end()
            self._buffer = new

    def paintEvent(self, event):
        p = QPainter(self)
        if self._buffer is not None:
            p.drawPixmap(0, 0, self._buffer)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._ensure_buffer()
            self.wb._last = ev.pos()
            self._stroke(ev.pos())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton and self.wb._last is not None:
            self._stroke(ev.pos())
            self.wb._last = ev.pos()

    def mouseReleaseEvent(self, ev):
        self.wb._last = None

    def _stroke(self, pos):
        if self._buffer is None:
            return
        p = QPainter(self._buffer)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.wb.tool == "eraser":
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            pen = QPen(QColor(0, 0, 0, 0), self.wb.width * 3,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin)
        else:
            pen = QPen(self.wb.color, self.wb.width,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(self.wb._last, pos)
        p.end()
        self.wb._has_strokes = True
        self.update()
        self.wb._mark_dirty()


class WhiteboardWidget(QWidget):
    """Drawing canvas with a pen/eraser/color/clear toolbar (D1)."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(255, 255, 255)
        self.tool = "pen"
        self.width = 3
        self._last = None
        self._dirty = False
        self._path = None
        self._has_strokes = False   # M5: "content" is strokes, not buffer state
        self._color_btns = []
        self._build()
        self.setMinimumSize(280, 280)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Whiteboard"))
        bar.addStretch()
        for hexc, name in (("#ffffff", "White"), ("#4a90d9", "Blue"),
                           ("#f44336", "Red"), ("#4caf50", "Green")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setToolTip(f"Pen color {name}")
            b.setAccessibleName(f"Pen color {name}")
            b.setProperty("hex", hexc)
            b.clicked.connect(self._pick_color)
            self._color_btns.append(b)
            bar.addWidget(b)
        self._color_btns[0].setChecked(True)
        self.eraser_btn = QPushButton("Eraser")
        self.eraser_btn.setCheckable(True)
        self.eraser_btn.setToolTip("Eraser")
        self.eraser_btn.setAccessibleName("Eraser tool")
        self.eraser_btn.clicked.connect(self._toggle_eraser)
        bar.addWidget(self.eraser_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip("Clear the whiteboard")
        clear_btn.setAccessibleName("Clear the whiteboard")
        clear_btn.clicked.connect(self.clear)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)
        self.canvas = _Canvas(self)
        layout.addWidget(self.canvas, 1)

    def _pick_color(self):
        btn = self.sender()
        hexc = btn.property("hex")
        self.color = QColor(hexc)
        self.tool = "pen"
        self.eraser_btn.setChecked(False)
        for b in self._color_btns:
            b.setChecked(b is btn)

    def _toggle_eraser(self, checked):
        self.tool = "eraser" if checked else "pen"
        for b in self._color_btns:
            b.setChecked(False)

    def _mark_dirty(self):
        self._dirty = True
        self.changed.emit()

    def clear(self):
        # M5: replace the buffer with a blank one (not None) and clear the
        # strokes flag — the debounced save then deletes the stale PNG so
        # the erased drawing can't resurrect on reopen.
        self.canvas._ensure_buffer()
        self.canvas._buffer.fill(QColor("#1e1e1e"))
        self._has_strokes = False
        self.canvas.update()
        self._mark_dirty()

    # ── persistence (D1) ─────────────────────────────────────────────────────
    def load_from_path(self, path):
        self._path = path
        self.canvas._buffer = None
        self._has_strokes = False
        if path:
            p = Path(path)
            if p.exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    self.canvas._buffer = pix
                    self._has_strokes = True
        self.canvas.update()
        self._dirty = False

    def has_content(self):
        return self._has_strokes

    def get_pixmap(self):
        return self.canvas._buffer

    def save_to_path(self, path):
        if self.canvas._buffer is not None:
            self.canvas._buffer.save(str(path))
        self._path = path
        self._dirty = False