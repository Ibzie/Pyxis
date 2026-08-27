import re
import os
from pathlib import Path
from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import (
    QTextCursor, QTextDocument, QTextDocumentFragment, QPageSize,
    QTextCharFormat, QFont, QColor, QTextOption, QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog,
)
from PyQt6.QtPrintSupport import QPrinter
from markdown_it import MarkdownIt
from markdown_it.common.normalize_url import validateLink as _default_validate_link
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

BG = "#1a1a1a"  # editor background

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


def _allow_file_link(url):
    """Allow `file:` URIs through markdown-it's link validator.

    markdown-it denies `file:` by default (BAD_PROTO_RE) as an XSS guard
    for browser contexts. Pyxis renders Markdown to a QTextDocument / PDF
    (never a browser) and resolves inline images to `file://` URIs, so the
    scheme must be permitted or `![alt](file://...)` is dropped as literal
    text and the bitmap never embeds (C1).
    """
    if url.strip().lower().startswith("file:"):
        return True
    return _default_validate_link(url)


def render_markdown_html(text):
    md = (MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": True})
          .enable("table").enable("strikethrough")
          .use(dollarmath_plugin).use(tasklists_plugin))
    md.validateLink = _allow_file_link
    html = md.render(text)
    html = re.sub(r'<span class="math inline">(.*?)</span>',
                  lambda m: latex_to_unicode(m.group(1)), html, flags=re.DOTALL)
    html = re.sub(r'<div class="math block">(.*?)</div>',
                  lambda m: f'<p style="text-align:center">{latex_to_unicode(m.group(1))}</p>',
                  html, flags=re.DOTALL)
    html = re.sub(r'<input[^>]*checked[^>]*>', '☑ ', html)
    html = re.sub(r'<input[^>]*>', '☐ ', html)
    return html


# Readable, widely-available serif stack for the PDF export. Qt substitutes
# the first family it can't find, so Georgia (Win/mac) falls back cleanly to
# DejaVu/Times on Linux.
EXPORT_FONT_FAMILY = "Georgia"
EXPORT_CSS = f"""
body {{ font-family: {EXPORT_FONT_FAMILY}, 'Palatino Linotype', 'DejaVu Serif', 'Times New Roman', serif; font-size: 11pt; }}
h1 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 24pt; font-weight: bold; margin: 14pt 0 6pt 0; }}
h2 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 20pt; font-weight: bold; margin: 12pt 0 5pt 0; }}
h3 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 17pt; font-weight: bold; margin: 10pt 0 4pt 0; }}
h4 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 15pt; font-weight: bold; margin: 9pt 0 4pt 0; }}
h5 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 13pt; font-weight: bold; margin: 8pt 0 3pt 0; }}
h6 {{ font-family: {EXPORT_FONT_FAMILY}, serif; font-size: 12pt; font-weight: bold; margin: 7pt 0 3pt 0; }}
p {{ margin: 0 0 8pt 0; }}
ul, ol {{ margin: 0 0 8pt 0; }}
li {{ margin: 0 0 2pt 0; }}
blockquote {{ margin: 4pt 0 8pt 14pt; color: #555555; }}
code {{ font-family: 'Courier New', 'DejaVu Sans Mono', monospace; font-size: 10pt; background-color: #f2f2f2; }}
pre {{ font-family: 'Courier New', 'DejaVu Sans Mono', monospace; font-size: 10pt; background-color: #f2f2f2; padding: 6pt; white-space: pre-wrap; }}
pre code {{ background-color: transparent; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #999999; padding: 4pt 6pt; word-wrap: break-word; }}
th {{ background-color: #efefef; }}
img {{ max-width: 100%; }}
hr {{ border: none; border-top: 1px solid #999999; margin: 10pt 0; }}
"""


def _export_html(body):
    """Wrap markdown-rendered HTML in a full document with our stylesheet,
    centering standalone image paragraphs based on the image's own width."""
    # Center a paragraph that contains only an image.
    body = re.sub(r'<p>\s*(<img[^>]*>)\s*</p>',
                  r'<p style="text-align:center">\1</p>', body)
    return (f'<html><head><meta charset="utf-8"><style>{EXPORT_CSS}</style>'
            f'</head><body>{body}</body></html>')


def _split_blocks(src):
    """Split markdown source into logical blocks for the live-preview editor.

    A block is a run of consecutive non-blank lines terminated by a blank
    line or EOF, except that fenced code blocks (``` / ~~~) are kept intact
    including any internal blank lines. Rejoining blocks with '\\n\\n'
    reproduces the (normalized) source.
    """
    blocks, cur, in_fence = [], [], False
    for line in src.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            cur.append(line)
            continue
        if not in_fence and line.strip() == "":
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks if blocks else [""]


def markdown_to_plain(src):
    """Project markdown to clean prose for TTS narration (B4).

    Strips syntax markers, replaces images with their alt text (or the word
    "image"), unwraps links/code, and drops fenced code blocks entirely so a
    blind user pressing `N` hears natural prose instead of literal
    `#`/`**`/`![alt](path)`.
    """
    src = re.sub(r'!\[([^\]]*)\]\([^)]+\)', lambda m: m.group(1) or "image", src)
    src = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', src)
    src = re.sub(r'^#{1,6}\s+', '', src, flags=re.MULTILINE)
    src = re.sub(r'\*\*([^*]+)\*\*', r'\1', src)
    src = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', src)
    src = re.sub(r'__([^_]+)__', r'\1', src)
    src = re.sub(r'`([^`]+)`', r'\1', src)
    src = re.sub(r'^```[^\n]*\n.*?^```[^\n]*\n?', '', src, flags=re.MULTILINE | re.DOTALL)
    src = re.sub(r'^- \[x\]\s*', 'done: ', src, flags=re.IGNORECASE | re.MULTILINE)
    src = re.sub(r'^- \[ \]\s*', 'todo: ', src, flags=re.MULTILINE)
    src = re.sub(r'^>\s?', '', src, flags=re.MULTILINE)
    src = re.sub(r'^---+\s*$', '', src, flags=re.MULTILINE)
    src = re.sub(r'\$([^$]+)\$', r'\1', src)
    src = re.sub(r'\n{3,}', '\n\n', src)
    return src.strip()


def _block_text(start_block, end_block=None):
    """Read the plain text of a logical block spanning QTextBlocks
    [start_block, end_block) — i.e. up to but not including `end_block`.
    If `end_block` is None, read to the end of the document (used when the
    focused block is the last one)."""
    out = []
    b = start_block
    while b.isValid() and (end_block is None or b != end_block):
        out.append(b.text())
        b = b.next()
    return "\n".join(out)


class _WysiwygEdit(QTextEdit):
    """Plain-text edit that strips U+FFFC object-replacement chars out of
    any pasted/inserted content (B2: a stray ￼ glyph used to discard image
    tracking and corrupt the saved note)."""

    def insertFromMimeData(self, mime):
        if mime.hasText():
            text = mime.text()
            if "\ufffc" in text:
                self.insertPlainText(text.replace("\ufffc", ""))
                return
        super().insertFromMimeData(mime)


class NotesPanel(QWidget):
    """Obsidian-style live-preview Markdown editor.

    Architecture: `_block_raw` (a list of markdown block strings) is the
    single source of truth; `_source` is its `\\n\\n`-join. The
    QTextDocument is a *rendered view* regenerated from the source:

    * the block under the cursor is shown as **raw markdown** (so the user
      can edit syntax markers directly — they're real characters here, not
      hidden ones),
    * every other block is rendered to formatted QTextDocumentFragments
      via `render_markdown_html` with **markers absent** (not recolored),
      so there is nothing to "un-hide" by typing between them (B3) and all
      constructs the export supports (code fences, tables, lists,
      strikethrough, block math) render live (B5).

    Inline images live only inside rendered (non-focused) blocks, inserted
    as QPixmap resources keyed by their `file://` URI; because the editable
    (focused) block shows the raw `![alt](path)` text instead of a pixmap,
    deleting an image can never reassign a *different* image's markdown
    (B1). Pasted U+FFFC is stripped (B2). Autosave is debounced and atomic
    (B6). `N` / narrator read a markdown-stripped projection (B4).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._block_raw = [""]
        self._block_starts = []          # QTextBlock at the start of each logical block
        self._focus = None               # index of the block shown raw
        self._base_dir = None
        self._callback = None
        self._render_lock = False        # suppress _on_edit during programmatic builds
        self._stream_heading = None
        self._stream_buffer = ""
        # Debounced autosave (B6): don't hit the disk on every keystroke.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self._flush_save)
        # Debounced re-render of the live view while streaming AI tokens.
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
        self.editor = _WysiwygEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setStyleSheet(
            "QTextEdit { background-color: " + BG + "; color: #ddd; border: 1px solid #444; "
            "padding: 8px; font-size: 14px; }")
        self.editor.textChanged.connect(self._on_edit)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)
        layout.addWidget(self.editor)

    # ── source model ────────────────────────────────────────────────────────
    def set_base_dir(self, path):
        self._base_dir = Path(path) if path else None

    def set_text(self, text):
        self._source = self._normalize(text)
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._focus = None
        self._rebuild_view()

    def get_text(self):
        return self._source

    def get_plain_text(self):
        """Markdown-stripped projection for TTS narration (B4)."""
        return markdown_to_plain(self._source)

    def on_save(self, callback):
        self._callback = callback

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

    def _sync_source(self):
        self._source = "\n\n".join(self._block_raw).rstrip() + "\n"
        self._schedule_save()

    def _schedule_save(self):
        self._save_timer.start()

    def _flush_save(self):
        if self._callback:
            self._callback(self._source)

    # ── rendered view ───────────────────────────────────────────────────────
    def _register_images(self, doc):
        """Pre-register every referenced image as a document resource so
        QTextDocumentFragment.fromHtml resolves <img src="file://…"> to the
        bitmap inline (and export embeds it — C1)."""
        if not self._base_dir:
            return
        for raw in self._block_raw:
            for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', raw):
                p = m.group(1)
                if p.startswith(("http", "file:")):
                    continue
                resolved = (self._base_dir / p).resolve()
                if not resolved.exists():
                    continue
                pix = QPixmap(str(resolved))
                if pix.isNull():
                    continue
                if pix.width() > 480:
                    pix = pix.scaledToWidth(
                        480, Qt.TransformationMode.SmoothTransformation)
                doc.addResource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(resolved.as_uri()), pix)

    def _render_block(self, raw, cursor):
        """Insert a rendered fragment for one block's raw markdown."""
        resolved = self._resolve_block(raw)
        html = render_markdown_html(resolved)
        cursor.insertFragment(QTextDocumentFragment.fromHtml(html))

    def _resolve_block(self, raw):
        """Rewrite relative image paths in one block to file:// URIs (only
        when the file exists; missing refs are left as-is — B7)."""
        if not self._base_dir:
            return raw

        def fix(m):
            p = m.group(1)
            if p.startswith(("http", "file:")):
                return m.group(0)
            resolved = (self._base_dir / p).resolve()
            if not resolved.exists():
                return m.group(0)
            return f"]({resolved.as_uri()})"
        return re.sub(r'\]\(([^)]+)\)', fix, raw)

    def _rebuild_view(self, keep_focus_on=None):
        """Rebuild the whole document from `_block_raw`.

        `keep_focus_on` is an optional (block_index, char_offset) hint for
        where to place the cursor after the rebuild (used on focus change).
        """
        doc = self.editor.document()
        self._render_lock = True
        doc.clear()
        self._register_images(doc)
        cursor = QTextCursor(doc)
        self._block_starts = []
        for i, raw in enumerate(self._block_raw):
            self._block_starts.append(doc.findBlock(cursor.position()))
            if i == self._focus:
                cursor.insertText(raw)
            else:
                self._render_block(raw, cursor)
            if i != len(self._block_raw) - 1:
                cursor.insertBlock()
        self._render_lock = False
        if keep_focus_on is not None:
            self._place_cursor(*keep_focus_on)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.editor.setTextCursor(cursor)

    def _place_cursor(self, blk_idx, offset):
        if not (0 <= blk_idx < len(self._block_starts)):
            return
        start = self._block_starts[blk_idx].position()
        end = (self._block_starts[blk_idx + 1].position()
               if blk_idx + 1 < len(self._block_starts)
               else self.editor.document().characterCount())
        pos = start + min(offset, max(0, end - start - 1))
        c = QTextCursor(self.editor.document())
        c.setPosition(max(start, pos))
        self.editor.setTextCursor(c)

    # ── editing ──────────────────────────────────────────────────────────────
    def _logical_block_at(self, cursor):
        """Return the index of the logical block containing the cursor."""
        bn = cursor.block().blockNumber()
        for i in range(len(self._block_starts) - 1, -1, -1):
            if self._block_starts[i].blockNumber() <= bn:
                return i
        return 0

    def _on_edit(self):
        if self._render_lock or self._focus is None:
            return
        doc = self.editor.document()
        start = self._block_starts[self._focus]
        end = (self._block_starts[self._focus + 1]
               if self._focus + 1 < len(self._block_starts) else None)
        text = _block_text(start, end)
        new_raw = _split_blocks(text)
        if len(new_raw) == 1:
            self._block_raw[self._focus] = new_raw[0]
            self._sync_source()
        else:
            # The focused block split (user pressed Enter twice → blank line).
            self._block_raw[self._focus:self._focus + 1] = new_raw
            cur = self.editor.textCursor()
            cur_blk = self._logical_block_at(cur)
            offset = cur.position() - self._block_starts[cur_blk].position()
            self._focus = None
            self._sync_source()
            self._rebuild_view(keep_focus_on=(cur_blk, offset))
            self._focus = cur_blk

    def _on_cursor_moved(self):
        if self._render_lock:
            return
        cur = self.editor.textCursor()
        idx = self._logical_block_at(cur)
        if idx == self._focus:
            return
        # Switch which block is raw: snapshot the old focus block's current
        # text (it was shown raw, so the document text IS its source), render
        # it, and show the new block raw. Cursor mapping is approximate.
        offset = cur.position() - self._block_starts[idx].position()
        old_focus = self._focus
        if old_focus is not None:
            start = self._block_starts[old_focus]
            end = (self._block_starts[old_focus + 1]
                   if old_focus + 1 < len(self._block_starts) else None)
            self._block_raw[old_focus] = _block_text(start, end)
        self._focus = idx
        self._sync_source()
        self._rebuild_view(keep_focus_on=(idx, offset))

    # ── programmatic append / AI streaming ─────────────────────────────────
    def append_markdown(self, block):
        if self._source and not self._source.endswith("\n\n"):
            self._source += "\n" if self._source.endswith("\n") else "\n\n"
        self._source += block.rstrip() + "\n\n"
        self._source = self._normalize(self._source)
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._focus = None
        self._rebuild_view()
        self._flush_save()

    def stream_start(self, heading):
        if self._source and not self._source.endswith("\n\n"):
            self._source += "\n" if self._source.endswith("\n") else "\n\n"
        self._stream_heading = heading
        self._source += heading + "\n"
        self._block_raw = _split_blocks(self._source)
        self._focus = None
        self._rebuild_view()

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
        self._block_raw = _split_blocks(self._source)
        self._focus = None
        self._rebuild_view()

    def stream_end(self):
        self._flush.stop()
        self._source = self._normalize(self._source)
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._focus = None
        self._rebuild_view()
        self._flush_save()
        self._stream_heading = None

    # ── PDF export ──────────────────────────────────────────────────────────
    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Notes as PDF", "notes.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        # Flush any pending edit so the exported doc matches the live source.
        self._save_timer.stop()
        self._flush_save()
        doc = QTextDocument()
        # Readable serif + word wrap that never lets a long line or code
        # token bleed past the page edge (Qt's rich text engine enforces it).
        doc.setDefaultFont(QFont(EXPORT_FONT_FAMILY, 11))
        _to = QTextOption()
        _to.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(_to)
        if self._base_dir:
            for raw in self._block_raw:
                for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', raw):
                    p = m.group(1)
                    if p.startswith(("http", "file:")):
                        continue
                    resolved = (self._base_dir / p).resolve()
                    if not resolved.exists():
                        continue
                    pix = QPixmap(str(resolved))
                    if pix.isNull():
                        continue
                    if pix.width() > 480:
                        pix = pix.scaledToWidth(
                            480, Qt.TransformationMode.SmoothTransformation)
                    doc.addResource(
                        QTextDocument.ResourceType.ImageResource,
                        QUrl(resolved.as_uri()), pix)
        doc.setHtml(_export_html(render_markdown_html(self._resolve_full(self._source))))
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc.print(printer)

    def _resolve_full(self, text):
        """Rewrite relative image paths in the whole source to file:// URIs."""
        if not self._base_dir:
            return text

        def fix(m):
            p = m.group(1)
            if p.startswith(("http", "file:")):
                return m.group(0)
            resolved = (self._base_dir / p).resolve()
            if not resolved.exists():
                return m.group(0)
            return f"]({resolved.as_uri()})"
        return re.sub(r'\]\(([^)]+)\)', fix, text)
