import re
from pathlib import Path
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import (
    QTextCursor, QTextDocument, QPageSize, QSyntaxHighlighter,
    QTextCharFormat, QFont, QColor, QTextOption,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog,
)
from PyQt6.QtPrintSupport import QPrinter
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin


# ── LaTeX → Unicode for PDF export ──────────────────────────────────────────
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
    "deg":"°","sqrt":"√","frac":"",  # handled specially
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
    """Full markdown → HTML with math→Unicode, for PDF export."""
    md = (
        MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": True})
        .enable("table").enable("strikethrough")
        .use(dollarmath_plugin).use(tasklists_plugin)
    )
    html = md.render(text)
    html = re.sub(r'<span class="math inline">(.*?)</span>',
                  lambda m: latex_to_unicode(m.group(1)), html, flags=re.DOTALL)
    html = re.sub(r'<div class="math block">(.*?)</div>',
                  lambda m: f'<p style="text-align:center">{latex_to_unicode(m.group(1))}</p>',
                  html, flags=re.DOTALL)
    html = re.sub(r'<input[^>]*checked[^>]*>', '☑ ', html)
    html = re.sub(r'<input[^>]*>', '☐ ', html)
    return html


# ── Syntax-highlighted single-panel editor ──────────────────────────────────
class _MarkdownHighlighter(QSyntaxHighlighter):
    """Styles markdown source in-place so the editor looks good while editable."""

    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []
        # H1-H6: bold + colored + larger
        for level, size in [(1, 20), (2, 17), (3, 15), (4, 14), (5, 13), (6, 13)]:
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(size)
            fmt.setForeground(QColor("#569cd6"))
            self._rules.append((re.compile(r'^' + '#' * level + r'\s+.*$'), fmt))
        # Bold **text**
        fmt = QTextCharFormat(); fmt.setFontWeight(QFont.Weight.Bold)
        fmt.setForeground(QColor("#ddd"))
        self._rules.append((re.compile(r'\*\*[^*]+\*\*'), fmt))
        # Italic *text*
        fmt = QTextCharFormat(); fmt.setFontItalic(True)
        fmt.setForeground(QColor("#c586c0"))
        self._rules.append((re.compile(r'(?<!\*)\*[^*]+\*(?!\*)'), fmt))
        # Inline code `text`
        fmt = QTextCharFormat(); fmt.setFontFamily("monospace")
        fmt.setForeground(QColor("#ce9178"))
        self._rules.append((re.compile(r'`[^`]+`'), fmt))
        # Blockquotes >
        fmt = QTextCharFormat(); fmt.setFontItalic(True)
        fmt.setForeground(QColor("#808080"))
        self._rules.append((re.compile(r'^>.*$'), fmt))
        # Math $...$
        fmt = QTextCharFormat(); fmt.setForeground(QColor("#b5cea8"))
        self._rules.append((re.compile(r'\$[^$]+\$'), fmt))
        # Block math $$...$$
        self._rules.append((re.compile(r'\$\$.*?\$\$', re.DOTALL), fmt))
        # Task list checkboxes
        fmt_done = QTextCharFormat(); fmt_done.setForeground(QColor("#4caf50"))
        self._rules.append((re.compile(r'- \[x\]'), fmt_done))
        fmt_todo = QTextCharFormat(); fmt_todo.setForeground(QColor("#FFC107"))
        self._rules.append((re.compile(r'- \[ \]'), fmt_todo))
        # Links [text](url)
        fmt = QTextCharFormat(); fmt.setForeground(QColor("#3794ff"))
        self._rules.append((re.compile(r'\[([^\]]+)\]\([^)]+\)'), fmt))
        # Horizontal rule
        fmt = QTextCharFormat(); fmt.setForeground(QColor("#444"))
        self._rules.append((re.compile(r'^---+$'), fmt))
        # Image embeds ![alt](path)
        fmt = QTextCharFormat(); fmt.setForeground(QColor("#d19a66"))
        self._rules.append((re.compile(r'!\[([^\]]*)\]\([^)]+\)'), fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class _AutoIndentEdit(QTextEdit):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            cursor = self.textCursor()
            indent = re.match(r'^(\s*)', cursor.block().text()).group(1)
            super().keyPressEvent(event)
            if indent:
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
        self.editor = _AutoIndentEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setStyleSheet(
            "QTextEdit { background-color: #1a1a1a; color: #ddd; border: 1px solid #444; "
            "padding: 8px; }")
        self.editor.textChanged.connect(self._on_edit)
        self._highlighter = _MarkdownHighlighter(self.editor.document())
        layout.addWidget(self.editor)

    def set_base_dir(self, path):
        self._base_dir = Path(path) if path else None

    def set_text(self, text):
        self._source = self._normalize(text)
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)

    def get_text(self):
        return self.editor.toPlainText()

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
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)
        if self._callback:
            self._callback(self._source)

    # ── AI streaming (buffered, throttled) ──────────────────────────────────
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
        self.editor.blockSignals(True)
        self.editor.setPlainText(self._source)
        self.editor.blockSignals(False)
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
        doc.setHtml(render_markdown_html(self._resolve(self._source)))
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc.print(printer)

    def on_save(self, callback):
        self._callback = callback

    def _on_edit(self):
        self._source = self.editor.toPlainText()
        if self._callback:
            self._callback(self._source)