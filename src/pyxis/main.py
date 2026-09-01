import sys, json, os, logging, logging.handlers, threading
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import Qt, QPoint, QThread, QTimer, QEventLoop, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QCursor, QAction, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QToolBar, QLabel, QLineEdit, QPushButton, QScrollArea, QFrame,
    QFileDialog, QMessageBox, QMenu, QListWidget, QListWidgetItem,
    QStatusBar, QSplitter, QInputDialog, QProgressBar, QWidgetAction,
    QSlider, QDialog, QTextEdit, QTabWidget, QCheckBox
)
from .pdf_engine import PdfEngine, ZOOM_LEVELS, PasswordRequired
from .page_view import PageView
from .notes_panel import NotesPanel
from .storage import (
    PdfStorage, a11y_onboarded, mark_a11y_onboarded,
    load_settings, save_settings,
)
from .ai_layer import AILayer, TIERS, detect_capacity, fit_level
from .ai_workers import LoadWorker, InferWorker, IndexWorker
from .speech import NarrationPlayer, VoiceLoadWorker, WavExportWorker
from .narrator import NarratorWorker
from .whiteboard import WhiteboardWidget


# Accessibility keybind reference — shown in the Help window and spoken
# aloud when the user presses `?` while in accessibility mode.
A11Y_KEYBINDS = [
    ("Ctrl+Shift+A", "Toggle accessibility mode on/off"),
    ("Space / P",    "Pause or resume narration"),
    ("R",            "Read the current page from the start"),
    ("C",            "Continue reading from your saved position"),
    ("S",            "Stop narration and clear the queue"),
    ("I",            "Describe the next image on the current page"),
    ("N",            "Read the notes panel aloud"),
    ("?",            "Open this help (and read it aloud)"),
    ("Esc",          "Stop narration / cancel AI / clear search"),
    ("Alt + ←/→",    "Go to the previous / next page"),
]


def _keybinds_text():
    """Plain-text rendering of A11Y_KEYBINDS for the Help dialog and TTS."""
    width = max(len(k) for k, _ in A11Y_KEYBINDS)
    lines = ["Accessibility keyboard shortcuts:", ""]
    for key, desc in A11Y_KEYBINDS:
        lines.append(f"  {key.ljust(width)}   {desc}")
    return "\n".join(lines)


class MainWindow(QMainWindow):
    def __init__(self, cli_path=None):
        super().__init__()
        self.engine = PdfEngine()
        self.storage = None
        self.pages = []
        self.zoom_index = 5
        self.zoom_level = 1.0
        self.fit_width = True
        self.current_page = 0
        self.search_results = []
        self.search_index = 0
        self.capture_mode = False
        self.ai = AILayer()
        self.ai_loader = None
        self.ai_infer = None
        self.rag_index = None
        self.index_worker = None
        self._rag_images = []
        # Accessibility (TTS + narrator)
        self._a11y_mode = False
        self._speech_engine = None
        self._player = None            # NarrationPlayer (render-then-play, E9)
        self._renderer = None          # NarratorWorker (PCM renderer)
        self._voice_loader = None      # A9: background Piper voice download
        self._img_worker = None        # ad-hoc image-description worker
        self._a11y_speed = 1.0   # multiplier
        self._a11y_volume = 1.0  # 0.0–1.0
        self._resume_pos = None     # last persisted (page, chunk)
        self._a11y_help_win = None  # Help dialog (kept alive for non-modal show)
        self._esc_target = None     # "ai" | "narration" — what Esc stops next (A3)
        # F5: debounces the full page re-render after a fit-width resize drag.
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(lambda: self._apply_zoom())
        # D1: debounced whiteboard autosave.
        self._whiteboard_timer = QTimer(self)
        self._whiteboard_timer.setSingleShot(True)
        self._whiteboard_timer.setInterval(500)
        self._whiteboard_timer.timeout.connect(self._save_whiteboard_now)
        # A11: low-vision UI settings (font scale / high contrast), persisted.
        self._font_scale = 1.0
        self._high_contrast = False
        self.setWindowTitle("Pyxis — PDF Reader")
        self.resize(1600, 900)
        self._build_toolbar()
        self._build_sidebar()
        self._build_notes_panel()
        self._build_viewer()
        self._apply_ui_settings()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        # H2: a visible busy indicator for the first-run voice download.
        self._voice_progress = QProgressBar()
        self._voice_progress.setRange(0, 0)
        self._voice_progress.setFixedWidth(160)
        self._voice_progress.setTextVisible(False)
        self._voice_progress.setVisible(False)
        self.status.addPermanentWidget(self._voice_progress)
        self.status.showMessage("Ready — Open a PDF file (Ctrl+O)")
        if cli_path:
            self.load_pdf(cli_path)

    def _theme_stylesheet(self):
        """Window-level background/text colors; high contrast is pure black/
        white for low-vision users (A11)."""
        if self._high_contrast:
            return "background-color: #000000; color: #ffffff;"
        return "background-color: #121212; color: #eeeeee;"

    def _apply_ui_settings(self):
        s = load_settings()
        self._font_scale = float(s.get("font_scale", 1.0)) or 1.0
        self._high_contrast = bool(s.get("high_contrast", False))
        self.setStyleSheet(self._theme_stylesheet())
        _apply_app_palette(QApplication.instance(), self._high_contrast)
        self._set_ui_scale(self._font_scale)

    def _set_ui_scale(self, scale):
        self._font_scale = scale
        base = 10.0 * scale
        app_font = QFont()
        app_font.setPointSizeF(max(6.0, base))
        QApplication.instance().setFont(app_font)
        if hasattr(self, "notes_panel"):
            self.notes_panel.set_ui_scale(scale)

    def _set_high_contrast(self, enabled):
        self._high_contrast = enabled
        self.setStyleSheet(self._theme_stylesheet())
        _apply_app_palette(QApplication.instance(), enabled)

    def _show_ui_settings(self):
        """Dialog to adjust UI font size and high-contrast colors (A11)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("UI Settings — font size & contrast")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Interface font size:"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(9, 22)
        slider.setValue(int(10.0 * self._font_scale))
        slider.setAccessibleName("Interface font size")
        layout.addWidget(slider)
        cont = QCheckBox("High-contrast colors (pure black & white)")
        cont.setChecked(self._high_contrast)
        cont.setAccessibleName("High-contrast colors")
        layout.addWidget(cont)
        row = QHBoxLayout()
        def apply():
            scale = slider.value() / 10.0
            self._set_ui_scale(scale)
            self._set_high_contrast(cont.isChecked())
            save_settings({"font_scale": scale, "high_contrast": cont.isChecked()})
            dlg.accept()
        ok = QPushButton("Apply")
        ok.setAccessibleName("Apply UI settings")
        ok.clicked.connect(apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        row.addStretch()
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)
        dlg.exec()

    def _build_toolbar(self):
        self.toolbar = QToolBar()
        self.addToolBar(self.toolbar)
        self.toolbar.setStyleSheet(
            "QToolBar { background: #1e1e1e; border: none; spacing: 4px; padding: 4px; }"
            "QPushButton { background: #333; color: #eee; border: none; padding: 4px 8px; }"
            "QPushButton:hover { background: #444; }"
            "QLineEdit { background: #2a2a2a; color: #eee; border: 1px solid #444; padding: 2px; }"
        )

        def _btn(text, tip, fn, checkable=False):
            """Toolbar button with a real name for OS screen readers (A6) —
            icon-only glyphs otherwise announce as '◀'/'🎧' etc. Buttons take
            no focus so a blind user's Space (pause narration) is never
            hijacked into clicking whichever button was last used."""
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            return b

        self.page_label = QLabel("0 / 0")
        self.page_label.setAccessibleName("Current page")
        self.zoom_label = QLabel("Fit Width")
        self.zoom_label.setAccessibleName("Zoom level")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setFixedWidth(200)
        self.search_box.setAccessibleName("Search PDF")
        self.search_box.returnPressed.connect(self.search)
        self.search_info = QLabel("")
        self.search_info.setAccessibleName("Search results")
        self.btn_open = _btn("Open", "Open PDF file (Ctrl+O)", self.open_file)
        self.btn_prev = _btn("◀", "Previous page", self.prev_page)
        self.btn_next = _btn("▶", "Next page", self.next_page)
        self.btn_zoom_out = _btn("−", "Zoom out", lambda: self._adjust_zoom(-1))
        self.btn_zoom_in = _btn("+", "Zoom in", lambda: self._adjust_zoom(1))
        self.btn_fit_width = _btn("⊞", "Toggle fit to width (Ctrl+0)", self.toggle_fit_width)
        self.btn_search_next = _btn("↓", "Next search result", lambda: self._navigate_search(1))
        self.btn_search_prev = _btn("↑", "Previous search result", lambda: self._navigate_search(-1))
        self.btn_clear_search = _btn("✕", "Clear search", self.clear_search)
        self.btn_sidebar = _btn("☰", "Toggle sidebar", self.toggle_sidebar)
        self.btn_notes = _btn("📝", "Toggle notes panel", self.toggle_notes)
        self.a11y_toggle_btn = _btn(
            "🎧", "Toggle accessibility mode (Ctrl+Shift+A)", self.toggle_a11y, checkable=True)
        self.btn_ui_settings = _btn(
            "Aa", "Interface font size & contrast", self._show_ui_settings)
        self.toolbar.addWidget(self.btn_open)
        self.toolbar.addWidget(self.btn_prev)
        self.toolbar.addWidget(self.page_label)
        self.toolbar.addWidget(self.btn_next)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.btn_zoom_out)
        self.toolbar.addWidget(self.zoom_label)
        self.toolbar.addWidget(self.btn_zoom_in)
        self.toolbar.addWidget(self.btn_fit_width)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.search_box)
        self.toolbar.addWidget(self.search_info)
        self.toolbar.addWidget(self.btn_search_next)
        self.toolbar.addWidget(self.btn_search_prev)
        self.toolbar.addWidget(self.btn_clear_search)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.btn_sidebar)
        self.toolbar.addWidget(self.btn_notes)
        self.toolbar.addWidget(self.a11y_toggle_btn)
        self.toolbar.addWidget(self.btn_ui_settings)
        self.toolbar.addSeparator()
        self.model_label = QPushButton("AI: idle")
        self.model_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.model_label.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #aaa; border: 1px solid #444; "
            "padding: 4px 10px; text-align: left; } QPushButton:hover { background: #333; }"
        )
        self.model_label.setToolTip("AI model status — click to load or switch")
        self.model_label.setAccessibleName("AI model status")
        self.model_label.clicked.connect(self.show_model_menu)
        self.toolbar.addWidget(self.model_label)
        self.ai_menu_btn = _btn("AI", "AI actions menu", self.show_ai_menu)
        self.toolbar.addWidget(self.ai_menu_btn)
        self.ai_progress = QProgressBar()
        self.ai_progress.setFixedWidth(200)
        self.ai_progress.setTextVisible(True)
        self.ai_progress.setStyleSheet(
            "QProgressBar { background: #2a2a2a; border: 1px solid #444; height: 16px; }"
            "QProgressBar::chunk { background: #4a90d9; }"
        )
        self.ai_progress.setVisible(False)
        self.ai_progress_lbl = QLabel("")
        self.ai_progress_lbl.setStyleSheet("color: #aaa;")
        self.ai_progress_lbl.setVisible(False)
        self.toolbar.addWidget(self.ai_progress_lbl)
        self.toolbar.addWidget(self.ai_progress)
        self._build_a11y_bar()

    def _build_a11y_bar(self):
        """Thin secondary toolbar with speed/volume/pause/continue/help.
        Hidden until accessibility mode is toggled on."""
        self.a11y_bar = QToolBar("Accessibility")
        self.a11y_bar.setStyleSheet(
            "QToolBar { background: #1a1a1a; border: none; spacing: 8px; padding: 4px; }"
            "QLabel { color: #aaa; }"
            "QSlider { width: 120px; }"
            "QSlider::groove:horizontal { background: #333; height: 4px; }"
            "QSlider::handle:horizontal { background: #4a90d9; width: 12px; "
            "margin: -4px 0; border-radius: 6px; }"
            "QPushButton { background: #333; color: #eee; border: none; padding: 4px 10px; }"
            "QPushButton:hover { background: #444; }"
            "QPushButton:checked { background: #4a90d9; color: #fff; }"
        )
        self.a11y_speed_lbl = QLabel("Speed: 1.0×")
        self.a11y_speed = QSlider(Qt.Orientation.Horizontal)
        self.a11y_speed.setRange(50, 200)
        self.a11y_speed.setValue(100)
        self.a11y_speed.setFixedWidth(120)
        self.a11y_speed.setToolTip("Narration speed (0.5×–2.0×)")
        self.a11y_speed.setAccessibleName("Narration speed")
        self.a11y_speed.valueChanged.connect(self._on_a11y_speed)
        self.a11y_vol_lbl = QLabel("Volume: 100%")
        self.a11y_volume = QSlider(Qt.Orientation.Horizontal)
        self.a11y_volume.setRange(0, 100)
        self.a11y_volume.setValue(100)
        self.a11y_volume.setFixedWidth(120)
        self.a11y_volume.setToolTip("Narration volume (0–100%)")
        self.a11y_volume.setAccessibleName("Narration volume")
        self.a11y_volume.valueChanged.connect(self._on_a11y_volume)
        self.a11y_play_btn = QPushButton("⏸ Pause")
        self.a11y_play_btn.setToolTip("Pause or resume narration")
        self.a11y_play_btn.setAccessibleName("Pause or resume narration")
        self.a11y_play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.a11y_play_btn.clicked.connect(self._toggle_pause)
        self.a11y_stop_btn = QPushButton("⏹ Stop")
        self.a11y_stop_btn.setToolTip("Stop narration and clear the queue")
        self.a11y_stop_btn.setAccessibleName("Stop narration and clear the queue")
        self.a11y_stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.a11y_stop_btn.clicked.connect(self._stop_narration)
        self.a11y_continue_btn = QPushButton("⏭ Continue")
        self.a11y_continue_btn.setToolTip("Continue reading from saved position")
        self.a11y_continue_btn.setAccessibleName("Continue reading from saved position")
        self.a11y_continue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.a11y_continue_btn.clicked.connect(self._continue_reading)
        self.a11y_help_btn = QPushButton("? Help")
        self.a11y_help_btn.setToolTip("Accessibility help (keyboard shortcuts)")
        self.a11y_help_btn.setAccessibleName("Accessibility help (keyboard shortcuts)")
        self.a11y_help_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.a11y_help_btn.clicked.connect(self._show_a11y_help)
        self.a11y_wav_btn = QPushButton("⏺ Save Audio")
        self.a11y_wav_btn.setToolTip("Export the current page's narration as a WAV file")
        self.a11y_wav_btn.setAccessibleName("Export the current page narration as WAV")
        self.a11y_wav_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.a11y_wav_btn.clicked.connect(self._export_page_wav)
        self.a11y_bar.addWidget(QLabel("🎧"))
        self.a11y_bar.addWidget(QLabel("Speed:"))
        self.a11y_bar.addWidget(self.a11y_speed)
        self.a11y_bar.addWidget(self.a11y_speed_lbl)
        self.a11y_bar.addSeparator()
        self.a11y_bar.addWidget(QLabel("Volume:"))
        self.a11y_bar.addWidget(self.a11y_volume)
        self.a11y_bar.addWidget(self.a11y_vol_lbl)
        self.a11y_bar.addSeparator()
        self.a11y_bar.addWidget(self.a11y_play_btn)
        self.a11y_bar.addWidget(self.a11y_stop_btn)
        self.a11y_bar.addWidget(self.a11y_continue_btn)
        self.a11y_bar.addWidget(self.a11y_help_btn)
        self.a11y_bar.addWidget(self.a11y_wav_btn)
        self.addToolBarBreak()  # second toolbar row below the main one
        self.addToolBar(self.a11y_bar)
        self.a11y_bar.setVisible(False)
        self._update_a11y_buttons()

    def _build_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(260)
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

    def _build_notes_panel(self):
        self.notes_panel = NotesPanel()
        self.notes_panel.on_save(self._save_notes)
        self.notes_panel.on_export(self._whiteboard_export_md)
        self.notes_panel.setMinimumWidth(220)
        # D1: Notes and a freehand Whiteboard live in the same right-hand tab.
        self.whiteboard = WhiteboardWidget()
        self.whiteboard.changed.connect(self._schedule_whiteboard_save)
        self.right_tabs = QTabWidget()
        self.right_tabs.setAccessibleName("Right panel")
        self.right_tabs.addTab(self.notes_panel, "Notes")
        self.right_tabs.addTab(self.whiteboard, "Whiteboard")
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)

    def _on_right_tab_changed(self, idx):
        # D1: leaving the Whiteboard tab persists any pending strokes.
        if self.right_tabs.indexOf(self.whiteboard) != idx:
            self._save_whiteboard_now()

    def _schedule_whiteboard_save(self):
        if self.storage:
            self._whiteboard_timer.start()

    def _save_whiteboard_now(self):
        # Save whenever the whiteboard reports a change — including Clear,
        # which must delete the stale PNG or the erased drawing resurrects
        # on reopen (M5).
        if not self.storage:
            return
        if self.whiteboard.has_content():
            self.storage.save_whiteboard(self.whiteboard.get_pixmap())
        else:
            self.storage.delete_whiteboard()

    def _whiteboard_export_md(self):
        """Extra markdown for notes-PDF export: the whiteboard image (D1)."""
        if not self.storage or not self.whiteboard.has_content():
            return ""
        self._save_whiteboard_now()
        return "## Whiteboard\n\n![whiteboard](whiteboard.png)"

    def _build_viewer(self):
        central = QWidget()
        self.setCentralWidget(central)
        hbox = QHBoxLayout(central)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
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
        self.splitter.addWidget(self.scroll)
        self.splitter.addWidget(self.right_tabs)
        # Let the PDF viewer and notes panel share available width equally on
        # resize (50/50), while the fixed-width sidebar takes no stretch.
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([260, 560, 560])
        hbox.addWidget(self.splitter)

    def _save_notes(self, text):
        if self.storage:
            self.storage.save_notes(text)

    def _start_indexing(self):
        self.rag_index = None
        if self.index_worker is not None and self.index_worker.isRunning():
            # L4: reassigning a running worker drops the last reference to a
            # live QThread (hard abort on exit) — cancel it and let it finish.
            self.index_worker.cancel()
            self.index_worker.wait(2000)
        self.index_worker = IndexWorker(self.engine)
        self.index_worker.progress.connect(self._on_index_progress)
        self.index_worker.done.connect(self._on_index_done)
        self.index_worker.failed.connect(self._on_index_failed)
        self.index_worker.start()

    def _on_index_progress(self, page, total, msg):
        if page == 0:
            self.status.showMessage(msg)

    def _on_index_done(self, rag):
        self.rag_index = rag
        # The persistent narration renderer may predate the index — point it
        # at the fresh one so R/C use chunked narration, not the raw fallback.
        if self._renderer is not None:
            self._renderer.set_rag(rag)
        # Populate image-block bboxes on each PageView for hit-testing + focus.
        for page in self.pages:
            blocks = [c["image_rect"] for c in rag.chunks
                      if c["page"] == page.page_idx and c.get("image_rect")]
            page.set_image_blocks(blocks)
        self.status.showMessage("Index ready — Ask AI can now cite pages")

    def _on_index_failed(self, msg):
        self.status.showMessage(f"Indexing failed: {msg}")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, path):
        password = None
        while True:
            try:
                self.engine.open(path, password=password)
                break
            except PasswordRequired:
                # G5: password-protected PDFs prompt instead of being rejected.
                if password is not None:
                    password = None
                    QMessageBox.warning(
                        self, "Pyxis", "That password was not correct. Try again.")
                password, ok = QInputDialog.getText(
                    self, "Password Required",
                    f"{Path(path).name} is password-protected. Enter the password:",
                    QLineEdit.EchoMode.Password)
                if not ok or not password:
                    QMessageBox.information(
                        self, "Pyxis", "Could not open the password-protected PDF.")
                    return
                continue
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{e}")
                return
        try:
            # PdfStorage does an unguarded mkdir here; an unwritable data
            # dir would otherwise raise PermissionError and (with no global
            # handler) SIGABRT the whole process.
            self.storage = PdfStorage(path)
            self.notes_panel.set_text(self.storage.load_notes())
            self.notes_panel.set_base_dir(self.storage.folder)
            self.whiteboard.load_from_path(self.storage.whiteboard_file)
            if self._renderer is not None:
                self._renderer.set_storage(self.storage)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load PDF:\n{e}")
            return
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
        self._apply_persisted_highlights()
        self.status.showMessage(f"Loaded {Path(path).name} — {self.engine.page_count} pages")
        self._start_indexing()

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
            page.describeImageRequested.connect(self._describe_image_at)
            page.set_chars(self.engine.get_text_chars(i))
            self.pages_layout.insertWidget(self.pages_layout.count() - 1, page)
            self.pages.append(page)
        self._apply_zoom()

    def _apply_zoom(self, render_visible_only=False):
        # No document loaded yet (e.g. Ctrl+0 pressed on the welcome
        # screen) — page_sizes is empty, so indexing it would SIGABRT.
        if not self.engine.doc or not self.engine.page_sizes or not self.pages:
            return
        if self.fit_width:
            # F4: mixed-size documents render each page at its own width
            # instead of clamping everything to page 0's width.
            avail = self.scroll.viewport().width() - 60
            self.zoom_level = avail / self.engine.page_sizes[0][0]
            self.zoom_label.setText("Fit Width")
        else:
            self.zoom_level = ZOOM_LEVELS[self.zoom_index]
            self.zoom_label.setText(f"{int(self.zoom_level * 100)}%")
        # Resizing every page is cheap; re-rendering is not (F5). Fit-width
        # re-renders only visible pages and lets the debounced full pass in
        # resizeEvent catch the rest — the LRU cache is never flushed here.
        for page in self.pages:
            if self.fit_width:
                page.set_zoom(avail / self.engine.page_sizes[page.page_idx][0])
            else:
                page.set_zoom(self.zoom_level)
        if render_visible_only:
            self._render_visible_pages()
        else:
            for page in self.pages:
                img = self.engine.render_page(page.page_idx, page.width())
                page.set_image(img)
        self.update_current_page(render=False)

    def _render_visible_pages(self):
        """Re-render only pages inside (or near) the current viewport (F5).
        Off-screen pages keep their last image and are re-rendered on scroll
        via update_current_page."""
        if not self.pages:
            return
        sb = self.scroll.verticalScrollBar()
        top = sb.value()
        bottom = top + self.scroll.viewport().height()
        for page in self.pages:
            py = page.mapTo(self.pages_widget, QPoint(0, 0)).y()
            h = page.height()
            if py + h >= top - h and py <= bottom + h:
                img = self.engine.render_page(page.page_idx, page.width())
                page.set_image(img)

    def _apply_persisted_highlights(self):
        if not self.storage:
            return
        for page in self.pages:
            hls = [h["bbox"] for h in self.storage.get_highlights_for_page(page.page_idx)]
            page.set_highlights(hls)

    def update_current_page(self, render=True):
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
        # F5: as pages scroll into view, give them a rendered bitmap (they were
        # skipped by the viewport-aware zoom pass). Cache hits make this cheap.
        # `render=False` from _apply_zoom avoids re-rendering what it just did.
        if render:
            self._render_visible_pages()

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

    def toggle_notes(self):
        self.right_tabs.setVisible(not self.right_tabs.isVisible())

    def bookmark_clicked(self, item):
        self.go_to_page(item.data(Qt.ItemDataRole.UserRole))

    def search(self):
        self.search_results = self.engine.search(self.search_box.text())
        self.search_index = 0
        if self.search_results:
            # F6: "1/N" now counts real in-page hits, not just pages.
            self.search_info.setText(f"1 / {len(self.search_results)}")
            self._show_search_hit(0)
        else:
            self.search_info.setText("0 / 0")
            self._apply_search_highlights()
            self.status.showMessage(f'No results for "{self.search_box.text()}"')

    def _apply_search_highlights(self):
        """Push every match's bbox to its page so matched text is highlighted
        on-page (F6)."""
        per_page = {}
        for page, bbox in self.search_results:
            per_page.setdefault(page, []).append(bbox)
        for p in self.pages:
            p.set_search_hits(per_page.get(p.page_idx, []))

    def _show_search_hit(self, idx):
        """Navigate to the given hit and scroll it into the viewport."""
        page, bbox = self.search_results[idx]
        self._apply_search_highlights()
        self.go_to_page(page)
        page_widget = self.pages[page]
        py = page_widget.mapTo(self.pages_widget, QPoint(0, 0)).y()
        y = int(py + bbox[1] * page_widget.zoom - self.scroll.viewport().height() / 2)
        self.scroll.verticalScrollBar().setValue(max(0, y))

    def _navigate_search(self, direction):
        if self.search_results:
            self.search_index = (self.search_index + direction) % len(self.search_results)
            self.search_info.setText(f"{self.search_index + 1} / {len(self.search_results)}")
            self._show_search_hit(self.search_index)

    def clear_search(self):
        self.search_box.clear()
        self.search_results = []
        self.search_index = 0
        self.search_info.setText("")
        for p in self.pages:
            p.set_search_hits([])

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
            menu.addAction("Add to Notes", lambda: self.add_highlight_to_notes(page))
        if hl_idx is not None:
            menu.addAction("Remove Highlight", lambda: self.remove_highlight(page_idx, hl_idx))
        if not selected_text and hl_idx is None:
            menu.addAction("Capture Screen", self.start_capture)
        menu.addSeparator()
        menu.addAction("Dismiss", menu.close)
        menu.exec(global_pos)

    def copy_selection(self, page):
        text = page.get_selection_text()
        if text:
            QApplication.clipboard().setText(text)
            self.status.showMessage("Copied to clipboard")
        page.clear_selection()

    def add_highlight_to_notes(self, page):
        text = page.get_selection_text()
        bbox = page.get_selection_bbox()
        if not text or not bbox or not self.storage:
            page.clear_selection()
            return
        img = self.engine.render_page(page.page_idx, page.width())
        x, y, x1, y1 = bbox
        sx, sy = int(x * page.zoom), int(y * page.zoom)
        sw, sh = int((x1 - x) * page.zoom), int((y1 - y) * page.zoom)
        cropped = img.copy(sx, sy, sw, sh)
        filepath, entry = self.storage.save_highlight(page.page_idx, cropped, bbox, text)
        page.highlights.append(bbox)
        page.update()
        rel = filepath.relative_to(self.storage.folder).as_posix()
        self.notes_panel.append_markdown(
            f"### Highlight — Page {page.page_idx + 1}\n\n"
            f"> {text}\n\n"
            f"![highlight]({rel})\n\n"
            f"_Page {page.page_idx + 1}_"
        )
        self.status.showMessage("Highlight added to notes")
        page.clear_selection()

    def remove_highlight(self, page_idx, hl_idx):
        if not self.storage:
            return
        self.storage.remove_highlight(page_idx, hl_idx)
        self._apply_persisted_highlights()
        self.status.showMessage("Highlight removed")

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
        if not rect or rect.width() < 10 or rect.height() < 10 or not self.storage:
            page.clear_selection()
            self.cancel_capture()
            return
        img = self.engine.render_page(page.page_idx, page.width())
        cropped = img.copy(rect)
        filepath, entry = self.storage.save_capture(page.page_idx, cropped)
        rel = filepath.relative_to(self.storage.folder).as_posix()
        self.notes_panel.append_markdown(
            f"### Capture — Page {page.page_idx + 1}\n\n"
            f"![capture]({rel})\n\n"
            f"_Page {page.page_idx + 1}_"
        )
        self.status.showMessage(f"Capture saved: {filepath.name}")
        page.clear_selection()
        self.cancel_capture()

    # ── AI layer ────────────────────────────────────────────────────────────
    def show_model_menu(self):
        ram, _ = detect_capacity()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1e1e1e; border: 1px solid #444; padding: 4px; }")
        last_family = None
        for i, tier in enumerate(TIERS):
            fam = tier.get("family", "")
            if fam != last_family:
                if last_family is not None:
                    menu.addSeparator()
                label = QLabel(
                    f"── {fam} {'(multimodal)' if tier.get('multimodal') else '(text only)'} ──")
                label.setStyleSheet(
                    "color: #888; padding: 6px 16px 2px 16px; "
                    "font-family: monospace; font-size: 12px; background: transparent;")
                wa = QWidgetAction(menu)
                wa.setDefaultWidget(label)
                wa.setEnabled(False)
                menu.addAction(wa)
                last_family = fam
            fit, color = fit_level(tier["footprint"], ram)
            mm = " 📷" if tier.get("multimodal") else ""
            btn = QPushButton(
                f"\u25cf  {tier['name']:<26} {fit:<10} ~{tier['footprint']:.1f} GB{mm}")
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 8px 16px; border: none; "
                "background: transparent; color: #eee; font-family: monospace; font-size: 13px; }"
                "QPushButton:hover { background: #333; }"
                f"QPushButton {{ color: {color}; }}"
            )
            idx = i
            btn.clicked.connect(
                lambda checked=False, idx=idx: (menu.close(), self._load_ai(idx)))
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(btn)
            menu.addAction(wa)
        if self.ai.is_loaded():
            menu.addSeparator()
            menu.addAction("Unload Model", self._unload_ai)
        menu.exec(QCursor.pos())

    def show_ai_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1e1e1e; color: #eee; border: 1px solid #444; }"
            "QMenu::item:selected { background-color: #333; }"
        )
        if not self.ai.is_loaded():
            menu.addAction("Load AI Model", self._load_ai)
        else:
            notes = self.notes_panel.get_text()
            menu.addAction("Summarize Notes", lambda: self._run_ai("summarize_notes", notes=notes))
            if self.engine.doc:
                idx = self.current_page
                txt = self.engine.extract_page_text(idx)
                menu.addAction("Summarize Current Page",
                               lambda: self._run_ai("summarize_page", page_text=txt, page_idx=idx))
            menu.addAction("Ask…", self._ai_ask)
            menu.addAction("Extract To-Dos", lambda: self._run_ai("extract_todos", notes=notes))
            menu.addAction("Draft Follow-up", lambda: self._run_ai("draft", notes=notes))
            menu.addAction("Suggest Tags", lambda: self._run_ai("suggest_tags", notes=notes))
        menu.addSeparator()
        if ((self.ai_infer and self.ai_infer.isRunning())
                or (self.ai_loader and self.ai_loader.isRunning())):
            menu.addAction("Cancel AI", self._cancel_ai)
        menu.exec(QCursor.pos())

    def _load_ai(self, tier_idx=None):
        if self.ai_loader and self.ai_loader.isRunning():
            return
        if self.ai_infer and self.ai_infer.isRunning():
            # E1: switching tiers mid-inference would double-load a model
            # without freeing the old one — the running generator still pins it.
            self.status.showMessage("AI busy — wait for it to finish (Esc to cancel)")
            self._speak("The AI is busy. Wait for it to finish, or press Escape to cancel.")
            return
        if self._renderer is not None and self._renderer.is_describing():
            # H1: freeing the model under a live vision call is a
            # use-after-free; the renderer can't abort mid-call either.
            self.status.showMessage(
                "AI busy describing an image — press Esc to stop narration first")
            self._speak("The AI is busy describing an image. "
                        "Press Escape to stop narration first.")
            return
        if self.ai.is_loaded():
            self.ai.unload()
        self.model_label.setText("AI: loading…")
        self.ai_loader = LoadWorker(self.ai, tier_idx=tier_idx)
        self.ai_loader.status.connect(self._ai_load_status)
        self.ai_loader.progress.connect(self._ai_load_progress)
        self.ai_loader.done.connect(self._ai_loaded)
        self.ai_loader.failed.connect(self._ai_failed)
        self.ai_loader.cancelled.connect(self._on_load_cancelled)
        self.ai_progress.setVisible(True)
        self.ai_progress_lbl.setVisible(True)
        self.ai_progress.setRange(0, 0)
        self.ai_progress.setValue(0)
        self.ai_progress_lbl.setText("AI: preparing…")
        self.ai_loader.start()

    def _unload_ai(self):
        if self.ai_infer and self.ai_infer.isRunning():
            # E1: freeing the model under an active generator would crash it.
            self.status.showMessage("AI busy — wait for it to finish (Esc to cancel)")
            return
        if self._renderer is not None and self._renderer.is_describing():
            self.status.showMessage(
                "AI busy describing an image — press Esc to stop narration first")
            return
        self.ai.unload()
        self.model_label.setText("AI: idle")
        self.model_label.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #aaa; border: 1px solid #444; "
            "padding: 4px 10px; text-align: left; } QPushButton:hover { background: #333; }")
        self.status.showMessage("AI model unloaded")

    def _ai_load_status(self, msg):
        if msg.startswith(("Detected", "Listing", "Downloading", "Loading")):
            self.ai_progress_lbl.setText(msg)
            if msg.startswith("Downloading"):
                self.model_label.setText("AI: downloading…")
            elif msg.startswith("Loading"):
                self.model_label.setText("AI: loading…")
        else:
            self.status.showMessage(msg)

    def _ai_load_progress(self, done, total, label):
        if total <= 0:
            self.ai_progress.setRange(0, 0)
            self.ai_progress.setValue(0)
            self.model_label.setText("AI: downloading…")
        else:
            self.ai_progress.setRange(0, total)
            self.ai_progress.setValue(done)
            pct = int(done / total * 100) if total else 0
            self.model_label.setText(f"AI: downloading {pct}%")
        self.ai_progress_lbl.setText(label or self.ai_progress_lbl.text())

    def _ai_loaded(self, label):
        self.ai_progress.setVisible(False)
        self.ai_progress_lbl.setVisible(False)
        self.model_label.setText(label.replace("AI: ", ""))
        self.model_label.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #4caf50; border: 1px solid #444; "
            "padding: 4px 10px; text-align: left; } QPushButton:hover { background: #333; }")
        self.status.showMessage(label)

    def _ai_failed(self, msg):
        self.ai_progress.setVisible(False)
        self.ai_progress_lbl.setVisible(False)
        self.model_label.setText("AI: error")
        self.model_label.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #f44336; border: 1px solid #444; "
            "padding: 4px 10px; text-align: left; } QPushButton:hover { background: #333; }")
        self.status.showMessage(f"AI error: {msg}")

    def _on_load_cancelled(self):
        """A model download/load was cancelled mid-flight (E4)."""
        self.ai_progress.setVisible(False)
        self.ai_progress_lbl.setVisible(False)
        self.model_label.setText("AI: idle")
        self.model_label.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #aaa; border: 1px solid #444; "
            "padding: 4px 10px; text-align: left; } QPushButton:hover { background: #333; }")
        self.status.showMessage("AI load cancelled")

    def _ai_ask(self):
        q, ok = QInputDialog.getText(self, "Ask AI", "Question:")
        if not ok or not q:
            return
        self.notes_panel.append_markdown(f"## Q — {q}")
        if self.rag_index and self.rag_index.is_ready:
            self.status.showMessage("AI: expanding query & retrieving context…")
            self._run_ai("answer_rag", question=q, rag=self.rag_index,
                         doc_title=Path(self.engine.path).stem)
        else:
            self._run_ai("answer", question=q, notes=self.notes_panel.get_text())

    def _run_ai(self, command, **kwargs):
        if not self.ai.is_loaded():
            self.status.showMessage("Load AI model first (toolbar → AI)")
            self._speak("Load an AI model first. Use the AI button in the toolbar.")
            return
        if self.ai_infer and self.ai_infer.isRunning():
            self.status.showMessage("AI busy — press Esc to cancel")
            return
        self._rag_images = []
        self.ai_infer = InferWorker(self.ai, command, **kwargs)
        self.ai_infer.heading.connect(self.notes_panel.stream_start)
        self.ai_infer.token.connect(self.notes_panel.stream_token)
        self.ai_infer.image_request.connect(self._render_rag_images)
        self.ai_infer.finished_ok.connect(self._on_infer_done)
        self.ai_infer.cancelled.connect(self._on_infer_cancelled)
        self.ai_infer.failed.connect(self._ai_failed)
        self.ai_infer.start()
        self._esc_target = "ai"
        self.status.showMessage(f"AI: {command.replace('_', ' ')}…  (Esc to cancel)")

    def _render_rag_images(self, image_chunks):
        if not self.storage or not self.engine.doc:
            return
        for chunk in image_chunks:
            page_idx = chunk["page"]
            if page_idx >= len(self.pages):
                continue
            page_widget = self.pages[page_idx]
            rect = chunk["image_rect"]
            img = self.engine.render_page(page_idx, page_widget.width())
            zoom = page_widget.zoom
            sx, sy = int(rect[0] * zoom), int(rect[1] * zoom)
            sw, sh = int((rect[2] - rect[0]) * zoom), int((rect[3] - rect[1]) * zoom)
            if sw < 10 or sh < 10:
                continue
            cropped = img.copy(sx, sy, sw, sh)
            filepath = self.storage.save_rag_image(page_idx, cropped)
            rel = filepath.relative_to(self.storage.folder).as_posix()
            self._rag_images.append(f"![context — Page {page_idx+1}]({rel})\n_Page {page_idx+1}_")

    def _on_infer_done(self, heading=None):
        self.notes_panel.stream_end()
        if self._rag_images:
            self.notes_panel.append_markdown("\n\n---\n\n" + "\n\n".join(self._rag_images))
            self._rag_images = []

    def _on_infer_cancelled(self, heading=None):
        """A run was cancelled mid-stream (E6) — mark the partial answer so it
        isn't mistaken for a complete one."""
        self.notes_panel.stream_end()
        self.notes_panel.append_markdown(
            "\n\n> ✂️ _Cancelled — answer may be incomplete_")
        self._rag_images = []
        self.status.showMessage("AI: cancelled")

    def _cancel_ai(self):
        if self._esc_target == "ai":
            self._esc_target = None
        if self.ai_loader and self.ai_loader.isRunning():
            # E4: a stalled/hung model download can now be cancelled.
            self.ai.request_cancel()
            self.status.showMessage("AI: cancelling download…")
        elif self.ai_infer and self.ai_infer.isRunning():
            self.ai.request_cancel()
            self.status.showMessage("AI: cancelling…")

    # ── Accessibility (TTS + narrator) ─────────────────────────────────────
    def toggle_a11y(self, checked=None):
        """Toggle accessibility mode on/off."""
        if checked is None:
            # Called from keyboard shortcut (Ctrl+Shift+A).
            checked = not self._a11y_mode
        if checked and not self._a11y_mode:
            self._a11y_on()
        elif not checked and self._a11y_mode:
            self._a11y_off()
        # Keep the toolbar 🎧 button's visual state honest when toggled via
        # the keyboard shortcut (A5).
        self.a11y_toggle_btn.setChecked(self._a11y_mode)

    def _a11y_on(self):
        self._a11y_mode = True
        self.a11y_bar.setVisible(True)
        # Restore slider values to the new engine (applied once it's ready).
        self._on_a11y_speed(self.a11y_speed.value(), quiet=True)
        self._on_a11y_volume(self.a11y_volume.value(), quiet=True)
        # Load any saved resume position for this PDF.
        if self.storage:
            pos = self.storage.get_narration_position()
            if pos is not None:
                self._resume_pos = (pos.get("page", 0), pos.get("chunk", 0))
        # A9: the Piper voice download (~65 MB on first run) blocks for tens
        # of seconds — run it on a QThread so the GUI stays responsive. If a
        # download is already in flight (e.g. a quick off→on toggle), let it
        # finish and bind via _on_voice_ready instead of spawning a second one.
        if self._voice_loader is not None and self._voice_loader.isRunning():
            self.status.showMessage("Accessibility: TTS voice still loading…")
            return
        self.status.showMessage("Accessibility: downloading/loading TTS voice…")
        self._voice_progress.setVisible(True)   # H2
        self._voice_loader = VoiceLoadWorker(self)
        self._voice_loader.status.connect(self._on_voice_status)
        self._voice_loader.done.connect(self._on_voice_ready)
        self._voice_loader.failed.connect(self._on_voice_failed)
        self._voice_loader.start()

    def _speak(self, text):
        """Speak a status/confirmation message when accessibility is active
        (A4) — blind users get no visual status bar, so gated errors and
        mode changes must be audible."""
        if self._a11y_mode and self._renderer is not None and text.strip():
            self._renderer.read_text(text)

    def _on_voice_status(self, msg):
        self.status.showMessage(f"TTS: {msg}")

    def _renderer_worker(self):
        """The persistent narration renderer, created once the TTS voice is
        ready and reused for the app's lifetime (E9): R/C/N and status speech
        all render to PCM here; the NarrationPlayer owns playback."""
        if self._renderer is None:
            self._renderer = NarratorWorker(
                self.engine, self.rag_index, self.ai, self.storage,
                self._speech_engine, self)
            self._renderer.chunk_ready.connect(self._on_chunk_ready)
            self._renderer.caption_ready.connect(self._on_caption_ready)
            self._renderer.render_status.connect(self.status.showMessage)
            self._renderer.render_done.connect(self._on_render_done)
            self._renderer.failed.connect(
                lambda m: self.status.showMessage(f"Narrator: {m}"))
            self._renderer.start()
        return self._renderer

    def _on_chunk_ready(self, samples, page, chunk, sr):
        """Renderer produced a sentence of PCM — hand it to the player (runs
        on the GUI thread; the player's timeline is lock-protected)."""
        if self._player is not None:
            self._player.append_chunk(samples, page, chunk, sr)

    def _on_render_done(self):
        """The renderer drained its job queue — playback may now run out."""
        if self._player is not None:
            self._player.render_finished()

    def _on_voice_ready(self, engine):
        # User may have toggled a11y off (or quit) while we were loading —
        # discard the engine instead of binding it.
        if not self._a11y_mode:
            try:
                engine.shutdown()
            except Exception:
                pass
            return
        self._speech_engine = engine
        # Push current slider settings to the freshly-loaded engine.
        self._speech_engine.set_rate(self._a11y_speed)
        if hasattr(self._speech_engine, "set_volume"):
            self._speech_engine.set_volume(self._a11y_volume)
        # E9: the player owns playback; the renderer synthesizes PCM chunks.
        self._player = NarrationPlayer(engine, self)
        self._player.state_changed.connect(self._on_player_state)
        self._player.position_changed.connect(self._on_position_played)
        self._player.page_finished.connect(self._on_page_played_to_end)
        self._player.failed.connect(lambda m: self.status.showMessage(f"TTS: {m}"))
        self._voice_loader = None
        self._voice_progress.setVisible(False)   # H2
        renderer = self._renderer_worker()
        self._player.begin()
        renderer.read_text(
            "Accessibility mode on. Press R to read the current page, "
            "C to continue, question mark for help.")
        # A7: first time accessibility is ever enabled, read the full shortcut
        # list aloud so the feature is discoverable without a screen reader.
        if not a11y_onboarded():
            mark_a11y_onboarded()
            renderer.read_text(_keybinds_text())
        self.status.showMessage(
            "Accessibility mode on — press R to read, C to continue, ? for help")
        self._update_a11y_buttons()

    def _on_voice_failed(self, msg):
        self._voice_loader = None
        self._voice_progress.setVisible(False)   # H2
        self.status.showMessage(f"TTS unavailable: {msg}")
        self._a11y_mode = False
        self.a11y_bar.setVisible(False)
        self.a11y_toggle_btn.setChecked(False)

    def _a11y_off(self):
        self._a11y_mode = False
        self.a11y_bar.setVisible(False)
        if self._renderer is not None:
            self._renderer.flush_jobs()
        if self._player is not None:
            # Speak the "off" confirmation on the way out, then drain & stop
            # (bounded wait so the engine isn't torn down mid-sentence, and
            # the GUI stays alive while it plays).
            self._player.begin()
            if self._renderer is not None:
                self._renderer.read_text("Accessibility mode off")
            loop = QEventLoop()
            timer = QTimer(self)
            timer.setSingleShot(True)

            def _done():
                timer.stop()
                loop.quit()

            timer.timeout.connect(loop.quit)
            self._player.state_changed.connect(
                lambda s: _done() if s in ("finished", "stopped") else None)
            timer.start(5000)
            loop.exec()
            try:
                self._player.state_changed.disconnect()
            except TypeError:
                pass
            self._player.stop()
            self._player = None
        if self._renderer is not None:
            self._renderer.stop()
            self._renderer = None
        if self._speech_engine:
            self._speech_engine.shutdown()
            self._speech_engine = None
        self._esc_target = None
        self._update_a11y_buttons()
        self.status.showMessage("Accessibility mode off")

    def _narrate(self, page, chunk=0, frame=0):
        """Common R/C path: abort stale audio, reset the player session, and
        render the page from (page, chunk[, frame])."""
        renderer = self._renderer_worker()
        renderer.flush_jobs()
        self._player.begin(start_at=(page, chunk, frame))
        renderer.read_page(page, start_chunk=chunk)
        self._esc_target = "narration"

    def _read_current_page(self):
        """Read the current page aloud via the narrator, from the top."""
        if not self._a11y_mode:
            self.toggle_a11y(True)
        if not self._player or not self._speech_engine:
            self.status.showMessage("TTS voice still loading…")
            return
        if not self.engine.doc:
            return
        self._narrate(self.current_page, 0, 0)
        self.status.showMessage(f"Reading page {self.current_page + 1}…")

    def _continue_reading(self):
        """Resume narration from the last-saved position (cross-session safe,
        sample-accurate within the saved chunk — E9)."""
        if not self._a11y_mode:
            self.toggle_a11y(True)
        if not self._player or not self._speech_engine:
            self.status.showMessage("TTS voice still loading…")
            return
        page, chunk, frame = self.current_page, 0, 0
        if self.storage:
            pos = self.storage.get_narration_position()
            if pos is not None:
                page = pos.get("page", page)
                chunk = pos.get("chunk", 0)
                frame = pos.get("frame", 0)
        elif self._resume_pos is not None:
            page, chunk = self._resume_pos
        if self.engine.doc and 0 <= page < self.engine.page_count:
            self.go_to_page(page)
            self._narrate(page, chunk, frame)
            self.status.showMessage(
                f"Continuing from page {page + 1}, chunk {chunk}…")
        else:
            # Saved position no longer valid — fall back to current page.
            self._narrate(self.current_page, 0, 0)
            self.status.showMessage(f"Reading page {self.current_page + 1}…")

    def _toggle_pause(self):
        """Pause/resume narration — a frame pointer in the player (E9), so
        resume continues mid-sentence exactly. Idle players ignore it."""
        if not self._player or not self._speech_engine:
            return
        if self._player.is_paused():
            self._player.resume()
            self.status.showMessage("Narration resumed")
        elif self._player.is_active():
            self._player.pause()
            # Persist the exact frame so Continue/C resumes mid-sentence.
            page, chunk, frame = self._player.current_position()
            if page is not None:
                self._resume_pos = (page, chunk)
                if self.storage:
                    self.storage.save_narration_position(page, chunk, frame)
            self.status.showMessage("Narration paused")

    def _on_a11y_speed(self, value, quiet=False):
        """Speed slider: value is 50–200 → 0.5×–2.0×. Baked into synthesis,
        so it applies to chunks not yet rendered (E9)."""
        self._a11y_speed = value / 100.0
        self.a11y_speed_lbl.setText(f"Speed: {self._a11y_speed:.1f}×")
        if self._speech_engine:
            self._speech_engine.set_rate(self._a11y_speed)
        if not quiet:
            self.status.showMessage(f"Narration speed: {self._a11y_speed:.1f}×")

    def _on_a11y_volume(self, value, quiet=False):
        """Volume slider: value is 0–100 → 0.0–1.0. Applied by the player at
        write time — live, mid-sentence (E9)."""
        self._a11y_volume = value / 100.0
        self.a11y_vol_lbl.setText(f"Volume: {value}%")
        if self._player:
            self._player.set_volume(self._a11y_volume)
        if self._speech_engine and hasattr(self._speech_engine, "set_volume"):
            self._speech_engine.set_volume(self._a11y_volume)
        if not quiet:
            self.status.showMessage(f"Narration volume: {value}%")

    def _on_player_state(self, state):
        """Player state transitions drive the toolbar buttons and status."""
        self._update_a11y_buttons()
        if state == "finished":
            if self._esc_target == "narration":
                self._esc_target = None
            self.status.showMessage("Narration finished")
        elif state == "underrun":
            self.status.showMessage("Rendering more audio…")

    def _update_a11y_buttons(self):
        """Drive the accessibility toolbar from the player's state: Pause is
        only usable while there's narration; Stop only while something is
        active; Continue only when idle — never mid-playback."""
        player = self._player
        active = player is not None and player.is_active()
        paused = player is not None and player.is_paused()
        ready = self._a11y_mode and self._speech_engine is not None
        self.a11y_play_btn.setEnabled(active)
        self.a11y_play_btn.setText("▶ Resume" if paused else "⏸ Pause")
        self.a11y_stop_btn.setEnabled(active)
        self.a11y_continue_btn.setEnabled(ready and not active)
        self.a11y_wav_btn.setEnabled(
            ready and self.engine.doc is not None
            and self.current_page < self.engine.page_count)

    def _on_position_played(self, page, chunk):
        """A chunk actually began playing — safe to persist this resume point
        (A2: never save positions ahead of what the user really heard)."""
        self._resume_pos = (page, chunk)
        if self.storage:
            frame = 0
            if self._player is not None:
                _, _, frame = self._player.current_position()
            self.storage.save_narration_position(page, chunk, frame)

    def _on_page_played_to_end(self, page):
        """The page's narration finished playing — advance the resume pointer
        to the top of the next page so 'Continue' doesn't replay this one."""
        if self._esc_target == "narration":
            self._esc_target = None
        if self.storage and self.engine.doc:
            nxt = min(page + 1, self.engine.page_count - 1)
            self._resume_pos = (nxt, 0)
            self.storage.save_narration_position(nxt, 0, 0)

    def _stop_narration(self):
        """Stop all narration and clear the audio timeline."""
        if self._esc_target == "narration":
            self._esc_target = None
        if self._renderer is not None:
            self._renderer.flush_jobs()
        if self._player is not None:
            self._player.stop()
        self.status.showMessage("Narration stopped")
        self._update_a11y_buttons()

    def _describe_next_image(self):
        """Describe the next image on the current page."""
        if not self.pages or self.current_page >= len(self.pages):
            return
        page = self.pages[self.current_page]
        bbox = page.next_image()
        if bbox is None:
            self.status.showMessage("No more images on this page")
            self._speak("No more images on this page.")
            return
        self._describe_image_at(page.page_idx, bbox)

    def _describe_image_at(self, page_idx, bbox):
        """Describe an image at the given page/bbox. Uses cache if available."""
        if not self.ai.is_loaded():
            self.status.showMessage("Load an AI model first (AI menu)")
            self._speak("Load an AI model first. Use the AI button in the toolbar.")
            return
        if not self.ai.is_multimodal():
            self.status.showMessage("Current model is text-only — switch to Gemma 4 for vision")
            self._speak("The current model is text only. Switch to a Gemma 4 model for vision.")
            return
        if getattr(self, "_img_worker", None) and self._img_worker.isRunning():
            # E2: one vision call at a time — a second one would pile onto the
            # same model object (and, without the AILayer lock, race narration).
            self.status.showMessage("Another image description is running — wait for it")
            self._speak("An image description is already running.")
            return
        cached = self.storage.get_image_description(page_idx, bbox)
        if cached:
            desc = cached["description"]
            self._on_caption_ready(desc, f"\n\n#### 📷 Page {page_idx+1} Figure\n\n{desc}\n")
            self._speak(f"Image on page {page_idx + 1}. {desc}")
            self.status.showMessage(f"Image (cached): {desc[:60]}")
            return
        # Extract image and describe via vision model.
        import fitz
        doc = fitz.open(self.engine.path)
        try:
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(clip=fitz.Rect(*bbox), matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes("png")
        finally:
            doc.close()
        self.status.showMessage(f"Describing image on page {page_idx+1}…")
        class _ImgWorker(QThread):
            done = pyqtSignal(str)
            def __init__(self, ai, png_bytes):
                super().__init__()
                self.ai = ai
                self.png = png_bytes
            def run(self):
                try:
                    self.done.emit(self.ai.describe_image(self.png))
                except Exception as e:
                    self.done.emit(f"Description unavailable: {e}")
        self._img_worker = _ImgWorker(self.ai, png_bytes)
        desc_box = [None]
        def on_desc(desc):
            img_path = self.storage.save_rag_image(page_idx, fitz.Pixmap(pix))
            self.storage.save_image_description(page_idx, bbox, desc, img_path)
            rel = img_path.relative_to(self.storage.folder).as_posix()
            self._on_caption_ready(desc, f"\n\n#### 📷 Page {page_idx+1} Figure\n\n{desc}\n\n![caption]({rel})\n")
            self._speak(f"Image on page {page_idx + 1}. {desc}")
            self.status.showMessage(f"Image: {desc[:60]}")
        self._img_worker.done.connect(on_desc)
        self._img_worker.start()

    def _on_caption_ready(self, desc, md):
        """Append a vision-model caption to the notes panel."""
        self.notes_panel.append_markdown(md)

    def _read_notes_aloud(self):
        """Read the notes panel text via TTS."""
        if not self._a11y_mode:
            self.toggle_a11y(True)
        if not self._player or not self._renderer:
            self.status.showMessage("TTS voice still loading…")
            return
        text = self.notes_panel.get_plain_text()
        if not text.strip():
            self._speak("The notes are empty.")
            return
        renderer = self._renderer_worker()
        renderer.flush_jobs()
        self._player.begin()
        renderer.read_text(text)
        self._esc_target = "narration"
        self.status.showMessage("Reading notes…")

    def _export_page_wav(self):
        """Export the current page's narration as a standalone WAV file (A10).
        Prefers the already-rendered timeline — image captions included, so
        the export is exactly what was narrated (E9); falls back to rendering
        the raw page text if the page was never narrated."""
        if not self._a11y_mode:
            self.toggle_a11y(True)
        if not self._speech_engine:
            self.status.showMessage("TTS voice still loading…")
            self._speak("The TTS voice is still loading.")
            return
        if not self.engine.doc or self.current_page >= self.engine.page_count:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Page Narration as WAV",
            f"page_{self.current_page + 1}.wav", "WAV Audio (*.wav)")
        if not path:
            return
        if not path.lower().endswith(".wav"):
            path += ".wav"
        if (self._player is not None
                and self._player.active_page() == self.current_page
                and self._player.save_wav(path)):
            self.status.showMessage(f"Audio saved: {path}")
            self._speak("Audio saved.")
            return
        text = self.engine.extract_page_text(self.current_page)
        if not text.strip():
            self.status.showMessage("No text on this page to export")
            self._speak("No text on this page to export.")
            return
        self.status.showMessage(f"Rendering page {self.current_page + 1} to audio…")
        worker = WavExportWorker(self._speech_engine, text, path, self)
        worker.done.connect(
            lambda p: (self.status.showMessage(f"Audio saved: {p}"),
                       self._speak("Audio saved.")))
        worker.failed.connect(
            lambda m: (self.status.showMessage(f"WAV export failed: {m}"),
                       self._speak("Audio export failed.")))
        self._wav_worker = worker
        worker.start()

    def _show_a11y_help(self):
        """Open the Accessibility Help window and read it aloud."""
        if not self._a11y_mode:
            self.toggle_a11y(True)
        dlg = self._a11y_help_win
        if dlg is None or not dlg.isVisible():
            dlg = QDialog(self)
            dlg.setWindowTitle("Pyxis — Accessibility Help")
            dlg.setMinimumWidth(420)
            layout = QVBoxLayout(dlg)
            layout.setContentsMargins(16, 16, 16, 16)
            head = QLabel("🎧 Accessibility — keyboard shortcuts")
            head.setStyleSheet("font-size: 15px; font-weight: bold; color: #4a90d9;")
            layout.addWidget(head)
            body = QTextEdit()
            body.setReadOnly(True)
            body.setStyleSheet(
                "QTextEdit { background-color: #1a1a1a; color: #ddd; "
                "border: none; font-family: monospace; font-size: 13px; }")
            body.setPlainText(_keybinds_text())
            body.setFixedHeight(220)
            layout.addWidget(body)
            tip = QLabel(
                "Tip: use the toolbar sliders for speed & volume, "
                "or press ? any time to hear this list again.")
            tip.setWordWrap(True)
            tip.setStyleSheet("color: #aaa; padding-top: 8px;")
            layout.addWidget(tip)
            close = QPushButton("Close")
            close.clicked.connect(dlg.close)
            layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
            dlg.show()
            self._a11y_help_win = dlg
        else:
            dlg.raise_()
            dlg.activateWindow()
        # Read it aloud too (interrupting any current narration).
        if self._renderer is not None and self._player is not None:
            self._renderer.flush_jobs()
            self._player.begin()
            self._renderer.read_text(_keybinds_text())
        self.status.showMessage("Accessibility help")

    def _scroll_document(self, event):
        """Route arrow / PageUp / Home / End keys to the document scroll
        area (F3) — the scroll bar is the only scrollable thing in the
        viewer and these keys were previously unreachable."""
        sb = self.scroll.verticalScrollBar()
        if event.key() == Qt.Key.Key_Up:
            sb.setValue(sb.value() - 80)
        elif event.key() == Qt.Key.Key_Down:
            sb.setValue(sb.value() + 80)
        elif event.key() == Qt.Key.Key_PageUp:
            sb.setValue(sb.value() - max(1, sb.pageStep()))
        elif event.key() == Qt.Key.Key_PageDown:
            sb.setValue(sb.value() + max(1, sb.pageStep()))
        elif event.key() == Qt.Key.Key_Home:
            sb.setValue(sb.minimum())
        elif event.key() == Qt.Key.Key_End:
            sb.setValue(sb.maximum())
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            if self.capture_mode:
                self.cancel_capture()
            elif (self._esc_target == "ai"
                    and ((self.ai_infer and self.ai_infer.isRunning())
                         or (self.ai_loader and self.ai_loader.isRunning()))):
                # A3: if the user last started an AI run, Esc cancels it first —
                # no longer requires two presses when narration is also running.
                self._cancel_ai()
            elif (self._esc_target == "narration" and self._a11y_mode
                    and self._player and self._player.is_active()):
                self._stop_narration()
            elif self.ai_infer and self.ai_infer.isRunning():
                self._cancel_ai()
            elif self.ai_loader and self.ai_loader.isRunning():
                self._cancel_ai()
            elif self._a11y_mode and self._player and self._player.is_active():
                self._stop_narration()
            else:
                self.clear_search()
            return
        # Document-view keyboard scrolling (F3) — a PageView is focusable, so
        # arrow/PageUp/Home/End reach this handler instead of dying on the
        # unfocused scroll area.
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp,
                           Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End):
            self._scroll_document(event)
            return
        # Accessibility shortcuts (no modifiers needed)
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and self._a11y_mode:
            k = event.key()
            if k in (Qt.Key.Key_Space, Qt.Key.Key_P):
                self._toggle_pause()
                return
            elif k == Qt.Key.Key_R:
                self._read_current_page()
                return
            elif k == Qt.Key.Key_C:
                self._continue_reading()
                return
            elif k == Qt.Key.Key_S:
                self._stop_narration()
                return
            elif k == Qt.Key.Key_I:
                self._describe_next_image()
                return
            elif k == Qt.Key.Key_N:
                self._read_notes_aloud()
                return
        # `?` needs Shift on most layouts, so handle it separately.
        if (self._a11y_mode and event.key() == Qt.Key.Key_Question
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier,
                                           Qt.KeyboardModifier.ShiftModifier)):
            self._show_a11y_help()
            return
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_A:
                self.toggle_a11y()
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
                self._stop_narration()
                self.next_page()
            elif event.key() == Qt.Key.Key_Left:
                self._stop_narration()
                self.prev_page()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_width and self.pages:
            # F5: during a live resize drag only re-render what's visible; a
            # debounced full pass catches off-screen pages once the drag stops.
            self._apply_zoom(render_visible_only=True)
            self._resize_timer.start(200)

    def closeEvent(self, event):
        # Stop accessibility workers first (TTS + narrator + voice loader).
        if self._voice_loader is not None and self._voice_loader.isRunning():
            self._a11y_mode = False  # so _on_voice_ready discards the engine
            self._voice_loader.wait(3000)
        if self._renderer is not None:
            self._renderer.stop()
        if self._player is not None:
            self._player.stop()
        if self._speech_engine:
            self._speech_engine.shutdown()
        if getattr(self, "_img_worker", None) and self._img_worker.isRunning():
            # A live vision call pins the model — unload() waits on the
            # inference lock, so a runaway call can't become a use-after-free.
            self.ai.request_cancel()
            self._img_worker.wait(3000)
        # Stop AI workers and free the model.
        for w in (self.ai_loader, self.ai_infer, self.index_worker):
            if w and w.isRunning():
                self.ai.request_cancel()
                w.quit()
                w.wait(3000)
        self.ai.unload()
        super().closeEvent(event)


def _install_excephook():
    """Install a global exception hook (F2) so an uncaught exception in any
    Qt slot or reimplemented virtual is logged to ai.log and surfaced via
    a modal error dialog instead of SIGABRT-ing the process (which would
    discard unsaved notes). Exceptions on worker threads are logged only;
    QThread workers already funnel their own errors through `failed`
    signals, and touching the GUI from a non-main thread is illegal."""
    log = logging.getLogger("pyxis")

    def hook(exc_type, exc_value, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, tb)
            return
        import traceback
        text = "".join(traceback.format_exception(exc_type, exc_value, tb))
        log.error("Unhandled exception:\n%s", text)
        if threading.current_thread() is not threading.main_thread():
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            QMessageBox.critical(
                None, "Pyxis — unexpected error",
                f"An unexpected error occurred and was contained.\n"
                f"The application will keep running, but please save your "
                f"notes and consider restarting.\n\n{exc_value}\n\n"
                f"Details written to ai.log.")
        except Exception:
            pass

    sys.excepthook = hook


def _apply_app_palette(app, high_contrast=False):
    """Dark (or high-contrast black/white) palette for the whole app (A11)."""
    p = app.palette()
    if high_contrast:
        p.setColor(p.ColorRole.Window, QColor(0, 0, 0))
        p.setColor(p.ColorRole.WindowText, QColor(255, 255, 255))
        p.setColor(p.ColorRole.Base, QColor(255, 255, 255))
        p.setColor(p.ColorRole.AlternateBase, QColor(220, 220, 220))
        p.setColor(p.ColorRole.Text, QColor(0, 0, 0))
        p.setColor(p.ColorRole.Button, QColor(0, 0, 0))
        p.setColor(p.ColorRole.ButtonText, QColor(255, 255, 255))
    else:
        p.setColor(p.ColorRole.Window, QColor(18, 18, 18))
        p.setColor(p.ColorRole.WindowText, QColor(238, 238, 238))
        p.setColor(p.ColorRole.Base, QColor(30, 30, 30))
        p.setColor(p.ColorRole.AlternateBase, QColor(40, 40, 40))
        p.setColor(p.ColorRole.Text, QColor(238, 238, 238))
        p.setColor(p.ColorRole.Button, QColor(50, 50, 50))
        p.setColor(p.ColorRole.ButtonText, QColor(238, 238, 238))
    app.setPalette(p)


def main():
    # Lean AI logging to ai.log (rotates at 1 MB, keeps 1 backup).
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from .storage import app_data_dir
    log_dir = app_data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        handlers=[logging.handlers.RotatingFileHandler(
            str(log_dir / "ai.log"), maxBytes=1_000_000, backupCount=1)],
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # E3: on NVIDIA machines whose bundled llama-cpp-python wheel is CPU-only,
    # download the CUDA-built libllama and restart so the native lib loads at
    # import time. If the restart can't be done (e.g. non-POSIX), fall through
    # to CPU rather than refusing to start.
    try:
        from .ai_layer import ensure_gpu_native
        if ensure_gpu_native():
            print("Installed CUDA build of llama — restarting to activate…")
            try:
                os.execv(sys.executable, [sys.executable, *sys.argv])
            except Exception:
                logging.getLogger("pyxis").warning("auto-restart failed; continuing on CPU")
    except Exception as e:
        logging.getLogger("pyxis").warning("GPU native setup failed: %s", e)
    app = QApplication(sys.argv)
    _install_excephook()  # F2: contain uncaught exceptions instead of SIGABRT
    app.setStyle("Fusion")
    _apply_app_palette(app)
    path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
