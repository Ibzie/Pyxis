import sys, json, os
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QLabel, QLineEdit, QPushButton, QScrollArea, QFrame,
    QFileDialog, QMessageBox, QMenu, QListWidget, QListWidgetItem,
    QStatusBar
)
from pdf_engine import PdfEngine, ZOOM_LEVELS
from page_view import PageView


class MainWindow(QMainWindow):
    def __init__(self, cli_path=None):
        super().__init__()
        self.engine = PdfEngine()
        self.pages = []
        self.zoom_index = 5
        self.zoom_level = 1.0
        self.fit_width = True
        self.current_page = 0
        self.search_results = []
        self.search_index = 0
        self.highlights = []
        self.capture_mode = False
        self.setWindowTitle("AI-PDF Reader")
        self.resize(1400, 900)
        self.setStyleSheet("background-color: #121212; color: #eeeeee;")
        self._build_toolbar()
        self._build_sidebar()
        self._build_viewer()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — Open a PDF file (Ctrl+O)")
        if cli_path:
            self.load_pdf(cli_path)

    def _build_toolbar(self):
        self.toolbar = QToolBar()
        self.addToolBar(self.toolbar)
        self.toolbar.setStyleSheet(
            "QToolBar { background: #1e1e1e; border: none; spacing: 4px; padding: 4px; }"
            "QPushButton { background: #333; color: #eee; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background: #444; }"
            "QLineEdit { background: #2a2a2a; color: #eee; border: 1px solid #444; padding: 2px; }"
        )
        self.page_label = QLabel("0 / 0")
        self.zoom_label = QLabel("Fit Width")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setFixedWidth(200)
        self.search_box.returnPressed.connect(self.search)
        self.search_info = QLabel("")
        self.toolbar.addWidget(QPushButton("Open", clicked=self.open_file))
        self.toolbar.addWidget(QPushButton("◀", clicked=self.prev_page))
        self.toolbar.addWidget(self.page_label)
        self.toolbar.addWidget(QPushButton("▶", clicked=self.next_page))
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QPushButton("−", clicked=lambda: self._adjust_zoom(-1)))
        self.toolbar.addWidget(self.zoom_label)
        self.toolbar.addWidget(QPushButton("+", clicked=lambda: self._adjust_zoom(1)))
        self.toolbar.addWidget(QPushButton("⊞", clicked=self.toggle_fit_width))
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.search_box)
        self.toolbar.addWidget(self.search_info)
        self.toolbar.addWidget(QPushButton("↓", clicked=lambda: self._navigate_search(1)))
        self.toolbar.addWidget(QPushButton("↑", clicked=lambda: self._navigate_search(-1)))
        self.toolbar.addWidget(QPushButton("✕", clicked=self.clear_search))
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QPushButton("☰", clicked=self.toggle_sidebar))

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(280)
        self.sidebar.setStyleSheet("background-color: #1a1a1a;")
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(8, 8, 8, 8)
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemClicked.connect(self.bookmark_clicked)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        layout.addWidget(QLabel("Bookmarks"))
        layout.addWidget(self.bookmark_list)
        layout.addSpacing(16)
        layout.addWidget(QLabel("Document Info"))
        layout.addWidget(self.info_label)
        layout.addStretch()

    def _build_viewer(self):
        central = QWidget()
        self.setCentralWidget(central)
        hbox = QHBoxLayout(central)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        hbox.addWidget(self.sidebar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: #121212; border: none;")
        self.scroll.verticalScrollBar().valueChanged.connect(self.update_current_page)
        self.pages_widget = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_widget)
        self.pages_layout.setSpacing(8)
        self.pages_layout.setContentsMargins(20, 20, 20, 20)
        self.pages_layout.addStretch()
        self.scroll.setWidget(self.pages_widget)
        hbox.addWidget(self.scroll)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, path):
        try:
            self.engine.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{e}")
            return
        self.highlights = []
        self.current_page = 0
        self.zoom_index = 5
        self.zoom_level = 1.0
        self.fit_width = True
        self.search_results = []
        self.search_index = 0
        self.search_box.clear()
        self.search_info.setText("")
        self._populate_bookmarks()
        self._update_info()
        self._rebuild_pages()
        self.status.showMessage(f"Loaded {Path(path).name} — {self.engine.page_count} pages")

    def _populate_bookmarks(self):
        self.bookmark_list.clear()
        for bm in self.engine.bookmarks:
            item = QListWidgetItem("  " * bm["level"] + bm["title"])
            item.setData(Qt.ItemDataRole.UserRole, bm["page"])
            self.bookmark_list.addItem(item)

    def _update_info(self):
        size = os.path.getsize(self.engine.path)
        size_str = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
        lines = [
            f"File: {Path(self.engine.path).name}",
            f"Size: {size_str}",
            f"Pages: {self.engine.page_count}",
            f"Version: {self.engine.version}",
        ]
        self.info_label.setText("\n".join(lines))

    def _rebuild_pages(self):
        for p in self.pages:
            p.deleteLater()
        self.pages = []
        while self.pages_layout.count() > 1:
            self.pages_layout.takeAt(0).widget().deleteLater()
        if not self.engine.doc:
            return
        for i in range(self.engine.page_count):
            w_pt, h_pt = self.engine.page_sizes[i]
            page = PageView(i, w_pt, h_pt)
            page.rightClicked.connect(self.show_context_menu)
            page.captureDone.connect(self.complete_capture)
            page.set_chars(self.engine.get_text_chars(i))
            self.pages_layout.insertWidget(self.pages_layout.count() - 1, page)
            self.pages.append(page)
        self._apply_zoom()

    def _apply_zoom(self):
        if self.fit_width:
            self.zoom_level = (self.scroll.viewport().width() - 60) / self.engine.page_sizes[0][0]
            self.zoom_label.setText("Fit Width")
        else:
            self.zoom_level = ZOOM_LEVELS[self.zoom_index]
            self.zoom_label.setText(f"{int(self.zoom_level * 100)}%")
        self.engine.invalidate_cache()
        for page in self.pages:
            page.set_zoom(self.zoom_level)
            img = self.engine.render_page(page.page_idx, page.width())
            page.set_image(img)
        self.update_current_page()

    def update_current_page(self):
        if not self.pages:
            return
        y = self.scroll.verticalScrollBar().value()
        mid = y + self.scroll.viewport().height() // 2
        for i, page in enumerate(self.pages):
            top = page.mapTo(self.pages_widget, QPoint(0, 0)).y()
            bottom = top + page.height()
            if top <= mid <= bottom:
                self.current_page = i
                break
        self.page_label.setText(f"{self.current_page + 1} / {self.engine.page_count}")

    def go_to_page(self, idx):
        if not self.pages or idx < 0 or idx >= len(self.pages):
            return
        self.current_page = idx
        y = self.pages[idx].mapTo(self.pages_widget, QPoint(0, 0)).y()
        self.scroll.verticalScrollBar().setValue(y)
        self.page_label.setText(f"{idx + 1} / {self.engine.page_count}")

    def next_page(self):
        self.go_to_page(min(self.current_page + 1, self.engine.page_count - 1))

    def prev_page(self):
        self.go_to_page(max(self.current_page - 1, 0))

    def _adjust_zoom(self, delta):
        if self.fit_width:
            self.fit_width = False
            self.zoom_index = 5
        else:
            self.zoom_index = max(0, min(len(ZOOM_LEVELS) - 1, self.zoom_index + delta))
        self._apply_zoom()

    def toggle_fit_width(self):
        self.fit_width = not self.fit_width
        if not self.fit_width:
            self.zoom_index = 5
        self._apply_zoom()

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def bookmark_clicked(self, item):
        self.go_to_page(item.data(Qt.ItemDataRole.UserRole))

    def search(self):
        self.search_results = self.engine.search(self.search_box.text())
        self.search_index = 0
        if self.search_results:
            self.search_info.setText(f"1 / {len(self.search_results)}")
            self.go_to_page(self.search_results[0])
        else:
            self.search_info.setText("0 / 0")
            self.status.showMessage(f'No results for "{self.search_box.text()}"')

    def _navigate_search(self, direction):
        if self.search_results:
            self.search_index = (self.search_index + direction) % len(self.search_results)
            self.search_info.setText(f"{self.search_index + 1} / {len(self.search_results)}")
            self.go_to_page(self.search_results[self.search_index])

    def clear_search(self):
        self.search_box.clear()
        self.search_results = []
        self.search_index = 0
        self.search_info.setText("")

    def show_context_menu(self, page_idx, global_pos, pdf_pos):
        page = self.pages[page_idx]
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1e1e1e; color: #eee; border: 1px solid #444; }"
            "QMenu::item:selected { background-color: #333; }"
        )
        selected_text = page.get_selection_text()
        screen_pos = QPoint(int(pdf_pos.x() * page.zoom), int(pdf_pos.y() * page.zoom))
        hl_idx = page.highlight_at(screen_pos)
        if selected_text:
            menu.addAction("Copy", lambda: self.copy_selection(page))
            menu.addAction("Highlight", lambda: self.save_highlight(page))
        if hl_idx is not None:
            menu.addAction("Remove Highlight", lambda: self.remove_highlight(page_idx, hl_idx))
        if not selected_text and hl_idx is None:
            menu.addAction("Screen Capture", self.start_capture)
        menu.addSeparator()
        menu.addAction("Dismiss", menu.close)
        menu.exec(global_pos)

    def copy_selection(self, page):
        text = page.get_selection_text()
        if text:
            QApplication.clipboard().setText(text)
            self.status.showMessage("Copied to clipboard")
        page.clear_selection()

    def save_highlight(self, page):
        bbox = page.get_selection_bbox()
        if bbox:
            self.highlights.append({"page": page.page_idx, "bbox": bbox})
            self._refresh_highlights()
            self.status.showMessage("Highlight saved")
        page.clear_selection()

    def remove_highlight(self, page_idx, hl_idx):
        count = 0
        kept = []
        for h in self.highlights:
            if h["page"] == page_idx:
                if count != hl_idx:
                    kept.append(h)
                count += 1
            else:
                kept.append(h)
        self.highlights = kept
        self._refresh_highlights()

    def _refresh_highlights(self):
        for page in self.pages:
            hls = [h["bbox"] for h in self.highlights if h["page"] == page.page_idx]
            page.set_highlights(hls)

    def start_capture(self):
        self.capture_mode = True
        self.status.showMessage("Capturing: drag to select region, Esc to cancel")
        for page in self.pages:
            page.set_capture_mode(True)

    def cancel_capture(self):
        self.capture_mode = False
        for page in self.pages:
            page.set_capture_mode(False)
        self.status.showMessage("Capture cancelled")

    def complete_capture(self, page_idx):
        page = self.pages[page_idx]
        rect = page.get_capture_rect()
        if not rect or rect.width() < 10 or rect.height() < 10:
            page.clear_selection()
            self.cancel_capture()
            return
        img = self.engine.render_page(page.page_idx, page.width())
        cropped = img.copy(rect)
        captures_dir = Path("captures")
        captures_dir.mkdir(exist_ok=True)
        base = Path(self.engine.path).stem if self.engine.path else "capture"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{base}_p{page.page_idx}_{ts}.png"
        filepath = captures_dir / filename
        cropped.save(str(filepath))
        json_path = captures_dir / f"{base}_annotations.json"
        data = {"captures": [], "highlights": []}
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
            except Exception:
                pass
        data["captures"].append({
            "type": "capture",
            "page": page.page_idx,
            "file": filename,
            "timestamp": datetime.now().isoformat(),
        })
        json_path.write_text(json.dumps(data, indent=2))
        self.status.showMessage(f"Capture saved: {filename}")
        page.clear_selection()
        self.cancel_capture()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.capture_mode:
                self.cancel_capture()
            else:
                self.clear_search()
            return
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_O:
                self.open_file()
            elif event.key() == Qt.Key.Key_0:
                self.toggle_fit_width()
            elif event.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self._adjust_zoom(1)
            elif event.key() == Qt.Key.Key_Minus:
                self._adjust_zoom(-1)
        elif event.modifiers() == Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Right:
                self.next_page()
            elif event.key() == Qt.Key.Key_Left:
                self.prev_page()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_width and self.pages:
            self._apply_zoom()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(18, 18, 18))
    palette.setColor(palette.ColorRole.WindowText, QColor(238, 238, 238))
    palette.setColor(palette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(40, 40, 40))
    palette.setColor(palette.ColorRole.Text, QColor(238, 238, 238))
    palette.setColor(palette.ColorRole.Button, QColor(50, 50, 50))
    palette.setColor(palette.ColorRole.ButtonText, QColor(238, 238, 238))
    app.setPalette(palette)
    path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
