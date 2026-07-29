import re
from pathlib import Path
from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import (
    QTextCursor, QTextDocument, QPageSize, QSyntaxHighlighter,
    QTextCharFormat, QFont, QColor, QTextOption, QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog,
)
from PyQt6.QtPrintSupport import QPrinter
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

BG = "#1a1a1a"  # editor background — used to hide syntax markers

GREEK = {
    "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","zeta":"ζ",
    "eta":"η","theta":"θ","iota":"ι","kappa":"κ","lambda":"λ","mu":"μ","nu":"ν",
    "xi":"ξ","pi":"π","rho":"ρ","sigma":"σ","tau":"τ","upsilon":"υ","phi":"φ",
    "chi":"χ","psi":"ψ","omega":"ω","Gamma":"Γ","Delta":"Δ","Theta":"Θ",
    "Lambda":"Λ","Xi":"Ξ","Pi":"Π","Sigma":"Σ","Phi":"Φ","Psi":"Ψ","Omega":"Ω",
}
SYMBOLS = {
    "leq":"≤","geq":"≥","neq":"≠","times":"×","div":"÷","pm":"±","infty":"∞",
    "sum":"∑","int":"∫","prod":"∏","partial":"∂","nabla":"∇","forall":"∀",
    "exists":"∃","in":"∈","notin":"∉","subset":"⊂","supset":"⊃","cup":"∪",
    "cap":"∩","emptyset":"∅","rightarrow":"→","to":"→","leftarrow":"←",
    "Rightarrow":"⇒","Leftarrow":"⇐","Leftrightarrow":"⇔","cdot":"·",
    "ldots":"…","approx":"≈","equiv":"≡","propto":"∝","perp":"⊥","circ":"∘",
    "deg":"°","sqrt":"√",
}
SUPER = str.maketrans("0123456789+-=()n","⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUB = str.maketrans("0123456789+-=()aeox","₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓ")


def latex_to_unicode(s):
    s = s.strip()
    for cmd, ch in {**GREEK, **SYMBOLS}.items():
        s = re.sub(r'\\' + cmd + r'(?![a-zA-Z])', ch, s)
    s = re.sub(r'\\sqrt\{([^}]+)\}', lambda m: '√'+m.group(1), s)
    s = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1)/(\2)', s)
    s = re.sub(r'\^\{([^}]+)\}', lambda m: m.group(1).translate(SUPER), s)
    s = re.sub(r'\^([a-zA-Z0-9])', lambda m: m.group(1).translate(SUPER), s)
    s = re.sub(r'_\{([^}]+)\}', lambda m: m.group(1).translate(SUB), s)
    s = re.sub(r'_([a-zA-Z0-9])', lambda m: m.group(1).translate(SUB), s)
    s = re.sub(r'\\text\{([^}]+)\}', r'\1', s)
    s = re.sub(r'\\([a-zA-Z]+)', r'\1', s)
    return s


def render_markdown_html(text):
    md = (MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": True})
          .enable("table").enable("strikethrough")
          .use(dollarmath_plugin).use(tasklists_plugin))
    html = md.render(text)
    html = re.sub(r'<span class="math inline">(.*?)</span>',
                  lambda m: latex_to_unicode(m.group(1)), html, flags=re.DOTALL)
    html = re.sub(r'<div class="math block">(.*?)</div>',
                  lambda m: f'<p style="text-align:center">{latex_to_unicode(m.group(1))}</p>',
                  html, flags=re.DOTALL)
    html = re.sub(r'<input[^>]*checked[^>]*>', '☑ ', html)
    html = re.sub(r'<input[^>]*>', '☐ ', html)
    return html


def _invisible():
    f = QTextCharFormat()
    f.setForeground(QColor(BG))
    return f


def _fmt(**kw):
    f = QTextCharFormat()
    if "bold" in kw: f.setFontWeight(QFont.Weight.Bold)
    if "italic" in kw: f.setFontItalic(True)
    if "color" in kw: f.setForeground(QColor(kw["color"]))
    if "size" in kw: f.setFontPointSize(kw["size"])
    if "mono" in kw: f.setFontFamily("monospace")
    return f


class _WysiwygHighlighter(QSyntaxHighlighter):
    """Hides markdown syntax markers (colored as background) so the text
    looks rendered while toPlainText() still returns the full markdown source."""

    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []
        # Headers: hide "# ", style the text
        for level, size in [(1, 22), (2, 18), (3, 16), (4, 14), (5, 13), (6, 13)]:
            self._rules.append((
                re.compile(r'^(' + '#' * level + r'\s+)(.*)$'),
                lambda m, f=_fmt(bold=True, color="#569cd6", size=size): [
                    (m.start(1), m.end(1), _invisible()),
                    (m.start(2), m.end(2), f),
                ]))
        # Bold: hide **, style content
        self._rules.append((
            re.compile(r'(\*\*)([^*]+)(\*\*)'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(bold=True, color="#ddd")),
                (m.start(3), m.end(3), _invisible()),
            ]))
        # Italic: hide *, style content
        self._rules.append((
            re.compile(r'(?<!\*)(\*)([^*]+)(\*)(?!\*)'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(italic=True, color="#c586c0")),
                (m.start(3), m.end(3), _invisible()),
            ]))
        # Inline code: hide `, style content
        self._rules.append((
            re.compile(r'(`)([^`]+)(`)'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(mono=True, color="#ce9178")),
                (m.start(3), m.end(3), _invisible()),
            ]))
        # Blockquote: hide "> "
        self._rules.append((
            re.compile(r'^(>\s*)(.*)$'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(italic=True, color="#808080")),
            ]))
        # Inline math $...$: hide $, style content
        self._rules.append((
            re.compile(r'(\$)([^$]+)(\$)'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(color="#b5cea8")),
                (m.start(3), m.end(3), _invisible()),
            ]))
        # Task list: hide - [x] / - [ ], show ☑/☐ via color trick
        self._rules.append((
            re.compile(r'^(- \[x\])(.*)$', re.IGNORECASE),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(color="#4caf50")),
            ]))
        self._rules.append((
            re.compile(r'^(- \[ \])(.*)$'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(color="#FFC107")),
            ]))
        # Links: hide [ and ](, style text
        self._rules.append((
            re.compile(r'(\[)([^\]]+)(\]\()([^)]+)(\))'),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(color="#3794ff", bold=True)),
                (m.start(3), m.end(5), _invisible()),
            ]))
        # Images: hide ![alt](path) — just dim it
        self._rules.append((
            re.compile(r'!\[([^\]]*)\]\([^)]+\)'),
            lambda m: [(m.start(), m.end(), _fmt(color="#d19a66"))]))
        # Horizontal rule: hide ---
        self._rules.append((
            re.compile(r'^(---+)$'),
            lambda m: [(m.start(1), m.end(1), _invisible())]))
        # Block math $$...$$
        self._rules.append((
            re.compile(r'(\$\$)(.*?)(\$\$)', re.DOTALL),
            lambda m: [
                (m.start(1), m.end(1), _invisible()),
                (m.start(2), m.end(2), _fmt(color="#b5cea8", size=12)),
                (m.start(3), m.end(3), _invisible()),
            ]))

    def highlightBlock(self, text):
        for pattern, formatter in self._rules:
            for m in pattern.finditer(text):
                try:
                    parts = formatter(m)
                    for start, end, fmt in parts:
                        self.setFormat(start, end - start, fmt)
                except Exception:
                    pass


def _convert_inline_math(text):
    """Replace $...$ with Unicode in a line of text."""
    def repl(m):
        return latex_to_unicode(m.group(1))
    return re.sub(r'\$([^$]+)\$', repl, text)


def _convert_checkboxes(text):
    text = re.sub(r'- \[x\]\s*', '☑ ', text, flags=re.IGNORECASE)
    text = re.sub(r'- \[ \]\s*', '☐ ', text)
    return text


class _WysiwygEdit(QTextEdit):
    """Plain-text editor that auto-converts math/checkboxes and auto-indents on Enter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._convert_on_enter = True

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            cursor = self.textCursor()
            # Convert math/checkboxes in the line being completed
            if self._convert_on_enter:
                line = cursor.block().text()
                converted = _convert_checkboxes(_convert_inline_math(line))
                if converted != line:
                    cursor.beginEditBlock()
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cursor.insertText(converted)
                    cursor.endEditBlock()
            # Auto-indent
            indent = re.match(r'^(\s*)', cursor.block().text()).group(1)
            # List continuation: "- item" → next line starts with "- "
            list_match = re.match(r'^(\s*)([-*]\s)', cursor.block().text())
            super().keyPressEvent(event)
            if list_match:
                self.textCursor().insertText(list_match.group(1) + list_match.group(2))
            elif indent:
                self.textCursor().insertText(indent)
        else:
            super().keyPressEvent(event)


class NotesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._base_dir = None
        self._callback = None
        self._stream_heading = None
        self._stream_buffer = ""
        self._flush = QTimer(self)
        self._flush.setInterval(80)
        self._flush.timeout.connect(self._drain)
        self._image_list = []        # markdown strings for inline images (in order)
        self._render_lock = False    # guard against recursive _on_edit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Notes"))
        bar.addStretch()
        self.btn_pdf = QPushButton("PDF")
        self.btn_pdf.clicked.connect(self.export_pdf)
        bar.addWidget(self.btn_pdf)
        layout.addLayout(bar)
        self.editor = _WysiwygEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setStyleSheet(
            "QTextEdit { background-color: " + BG + "; color: #ddd; border: 1px solid #444; "
            "padding: 8px; font-size: 14px; }")
        self.editor.textChanged.connect(self._on_edit)
        self._highlighter = _WysiwygHighlighter(self.editor.document())
        layout.addWidget(self.editor)

    def set_base_dir(self, path):
        self._base_dir = Path(path) if path else None

    def set_text(self, text):
        self._source = self._normalize(text)
        self._render_lock = True
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)
        self._render_images()
        self._render_lock = False

    def get_text(self):
        return self._source

    def _normalize(self, text):
        lines = [line.rstrip() for line in text.split("\n")]
        out, blank = [], 0
        for line in lines:
            if line == "":
                blank += 1
                if blank <= 1:
                    out.append("")
            else:
                blank = 0
                out.append(line)
        return "\n".join(out).rstrip() + "\n"

    def append_markdown(self, block):
        if self._source and not self._source.endswith("\n\n"):
            self._source += "\n" if self._source.endswith("\n") else "\n\n"
        self._source += block.rstrip() + "\n\n"
        self._source = self._normalize(self._source)
        self._render_lock = True
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)
        self._render_images()
        self._render_lock = False
        if self._callback:
            self._callback(self._source)

    # ── AI streaming ────────────────────────────────────────────────────────
    def stream_start(self, heading):
        if self._source and not self._source.endswith("\n\n"):
            self._source += "\n" if self._source.endswith("\n") else "\n\n"
        self._stream_heading = heading
        self._source += heading + "\n"
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)

    def stream_token(self, tok):
        if self._stream_heading is None:
            return
        self._stream_buffer += tok
        self._source += tok
        if not self._flush.isActive():
            self._flush.start()

    def _drain(self):
        if not self._stream_buffer:
            self._flush.stop()
            return
        self._stream_buffer = ""
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)

    def stream_end(self):
        self._flush.stop()
        self._source = self._normalize(self._source)
        self._render_lock = True
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)
        self._render_images()
        self._render_lock = False
        if self._callback:
            self._callback(self._source)
        self._stream_heading = None

    # ── PDF export ──────────────────────────────────────────────────────────
    def _resolve(self, text):
        if not self._base_dir:
            return text
        def fix(m):
            p = m.group(1)
            if p.startswith(("http", "file:")):
                return m.group(0)
            return f"]({(self._base_dir / p).resolve().as_uri()})"
        return re.sub(r'\]\(([^)]+)\)', fix, text)

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Notes as PDF", "notes.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        doc = QTextDocument()
        # Pre-register every referenced image as a QTextDocument resource so
        # setHtml can render them inline. Without this, <img src="file://…">
        # tags produce a broken-path stub in the exported PDF (the image path
        # was printed instead of the bitmap).
        if self._base_dir:
            for m in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', self._source):
                p = m.group(2)
                if p.startswith(("http", "file:")):
                    continue
                resolved = (self._base_dir / p).resolve()
                if not resolved.exists():
                    continue
                pix = QPixmap(str(resolved))
                if pix.isNull():
                    continue
                max_w = 480
                if pix.width() > max_w:
                    pix = pix.scaledToWidth(
                        max_w, Qt.TransformationMode.SmoothTransformation)
                doc.addResource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(resolved.as_uri()), pix)
        doc.setHtml(render_markdown_html(self._resolve(self._source)))
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc.print(printer)

    def on_save(self, callback):
        self._callback = callback

    def _render_images(self):
        """Replace ![alt](path) text with actual inline images.
        Tracks original markdown in _image_list so get_text() returns full source."""
        doc = self.editor.document()
        text = doc.toPlainText()
        img_re = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        matches = list(img_re.finditer(text))
        if not matches:
            self._image_list = []
            return
        self._image_list = []
        cursor = QTextCursor(doc)
        # Process in reverse so positions don't shift
        for m in reversed(matches):
            full_md = m.group(0)
            path = m.group(2)
            if path.startswith(("http", "file:")):
                resolved = path
            elif self._base_dir:
                resolved = str((self._base_dir / path).resolve())
            else:
                resolved = path
            pix = QPixmap(resolved) if not resolved.startswith("http") else None
            if pix is None or pix.isNull():
                self._image_list.insert(0, full_md)
                continue
            max_w = 480
            if pix.width() > max_w:
                pix = pix.scaledToWidth(
                    max_w, Qt.TransformationMode.SmoothTransformation)
            idx = len(self._image_list)
            url = QUrl(f"img://{idx}")
            doc.addResource(QTextDocument.ResourceType.ImageResource, url, pix)
            cursor.setPosition(m.start())
            cursor.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertImage(url.toString())
            self._image_list.insert(0, full_md)
        self._highlighter.setDocument(doc)  # re-highlight after image insertion

    def _on_edit(self):
        if self._render_lock:
            return
        raw = self.editor.toPlainText()
        parts = raw.split('\ufffc')  # U+FFFC = inline image object
        n_imgs = len(parts) - 1
        if n_imgs == len(self._image_list):
            self._source = parts[0]
            for i, md in enumerate(self._image_list):
                self._source += md + parts[i + 1]
        elif n_imgs < len(self._image_list):
            self._image_list = self._image_list[:n_imgs]
            self._source = parts[0]
            for i, md in enumerate(self._image_list):
                self._source += md + parts[i + 1]
        else:
            self._source = raw
        if self._callback:
            self._callback(self._source)