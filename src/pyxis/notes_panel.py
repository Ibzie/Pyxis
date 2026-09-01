import re
import os
import gc
import time
from pathlib import Path
from PyQt6.QtCore import QTimer, Qt, QUrl, QSizeF, QMarginsF
from PyQt6.QtGui import (
    QTextCursor, QTextDocument, QTextDocumentFragment, QPageSize,
    QFont, QTextOption, QPixmap, QPdfWriter, QPageLayout, QKeySequence,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QFileDialog, QMessageBox,
)
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
EXPORT_MARGINS_MM = 15.0
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
pre {{ font-family: 'Courier New', 'DejaVu Sans Mono', monospace; font-size: 10pt; background-color: #f2f2f2; padding: 6pt; }}
pre code {{ background-color: transparent; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #999999; padding: 4pt 6pt; }}
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
    including any internal blank lines. Rejoining blocks with '\n\n'
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

class _WysiwygEdit(QTextEdit):
    """Plain-text edit bound to its NotesPanel for edit interception.

    Strips U+FFFC object-replacement chars out of any pasted/inserted
    content (B2: a stray ￼ glyph used to discard image tracking and corrupt
    the saved note), drives custom undo/redo over the panel's markdown-block
    snapshots (Qt's internal undo would fight the live-preview renderer),
    and intercepts Backspace/Delete at logical block boundaries so Qt never
    merges a raw block into a *rendered* one — the merge happens at the
    markdown level instead, losslessly.
    """

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.setUndoRedoEnabled(False)

    def insertFromMimeData(self, mime):
        if mime.hasText():
            text = mime.text()
            if "\ufffc" in text:
                self.insertPlainText(text.replace("\ufffc", ""))
                return
        super().insertFromMimeData(mime)

    def keyPressEvent(self, ev):
        p = self._panel
        if ev.matches(QKeySequence.StandardKey.Undo):
            p._undo()
            ev.accept()
            return
        if ev.matches(QKeySequence.StandardKey.Redo):
            p._redo()
            ev.accept()
            return
        cur = self.textCursor()
        if not cur.hasSelection():
            if ev.key() == Qt.Key.Key_Backspace and p._at_region_start(cur):
                p._merge_with_prev()
                ev.accept()
                return
            if ev.key() == Qt.Key.Key_Delete and p._at_region_end(cur):
                p._merge_with_next()
                ev.accept()
                return
        super().keyPressEvent(ev)


class NotesPanel(QWidget):
    """Obsidian-style live-preview Markdown editor.

    Architecture: `_block_raw` (a list of markdown block strings) is the
    single source of truth; `_source` is its `\n\n`-join. The QTextDocument
    is a *rendered view* regenerated from the source:

    * the block under the cursor is shown as **raw markdown** (so the user
      can edit syntax markers directly — they're real characters here, not
      hidden ones),
    * every other block is rendered to formatted QTextDocumentFragments via
      `render_markdown_html` with **markers absent** (B3, B5).

    Editing is reconciled through the document's `contentsChange(pos,
    removed, added)` signal, which pinpoints exactly which characters
    changed. Edits contained in a raw block sync straight back into
    `_block_raw`; edits that cross block boundaries (multi-block selection
    deletes, select-all, merges) splice the affected blocks from the
    document text — so deleted content STAYS deleted instead of
    resurrecting on the next rebuild. Boundary Backspace/Delete keys are
    intercepted and merged at the markdown level (lossless — the old code
    let Qt merge raw text into rendered fragments and desync). Undo/redo
    runs over `_block_raw` snapshots (Qt undo disabled). Pasted U+FFFC is
    stripped (B2). Autosave is debounced and atomic (B6). `N` / narrator
    read a markdown-stripped projection (B4). AI streaming updates only the
    streaming block's region in place — no whole-document flicker, and the
    user's cursor survives appends.
    """

    UNDO_COALESCE_S = 1.2
    UNDO_STACK_MAX = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._block_raw = [""]
        self._block_pos = []          # char position of each logical block's region
        self._doc_len = 0             # document characterCount at last sync
        self._focus = None            # index of the block shown raw
        self._raw_blocks = set()      # blocks shown raw: focus + streaming block
        self._base_dir = None
        self._callback = None
        self._export_extra = None     # optional callable → extra markdown (D1)
        self._render_lock = False     # suppress reconcile during programmatic builds
        # Custom undo over markdown-block snapshots.
        self._undo_stack = []         # (block_raw copy, focus, (blk_idx, offset))
        self._redo_stack = []
        self._undo_last_t = 0.0
        self._undo_last_focus = None
        # AI streaming state.
        self._stream_idx = None       # logical block receiving streamed tokens
        self._stream_text = ""        # authoritative raw text of that block
        self._stream_buffer = ""      # tokens not yet flushed to the view
        # Debounced autosave (B6): don't hit the disk on every keystroke.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self._flush_save)
        # Debounced re-render of the streaming block while AI tokens arrive.
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
        self.editor = _WysiwygEdit(self)
        self.editor.setAcceptRichText(False)
        self.editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setStyleSheet(
            "QTextEdit { background-color: " + BG + "; color: #ddd; border: 1px solid #444; "
            "padding: 8px; font-size: 14px; }")
        # Reconciliation rides on contentsChange (fires for every edit path:
        # keyboard, context-menu, middle-click paste, IME); cursor moves
        # switch which block is raw.
        self.editor.document().contentsChange.connect(self._on_contents_change)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)
        layout.addWidget(self.editor)

    # ── source model ────────────────────────────────────────────────────────
    def set_base_dir(self, path):
        self._base_dir = Path(path) if path else None

    def set_ui_scale(self, scale):
        """Scale the editor font size for low-vision users (A11)."""
        size = max(9, int(14 * scale))
        self.editor.setStyleSheet(
            f"QTextEdit {{ background-color: {BG}; color: #ddd; "
            f"border: 1px solid #444; padding: 8px; font-size: {size}px; }}")

    def set_text(self, text):
        self._source = self._normalize(text)
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._focus = None
        self._raw_blocks = set()
        self._stream_idx = None
        self._stream_text = ""
        self._stream_buffer = ""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._rebuild_view()

    def get_text(self):
        return self._source

    def get_plain_text(self):
        """Markdown-stripped projection for TTS narration (B4)."""
        return markdown_to_plain(self._source)

    def on_save(self, callback):
        self._callback = callback

    def on_export(self, callback):
        """Register a callback returning extra markdown to include in the PDF
        export (D1 — the MainWindow appends the whiteboard tab's content so it
        isn't silently dropped)."""
        self._export_extra = callback

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

    # ── rendered view ────────────────────────────────────────────────────────
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
        """Rebuild the whole document from `_block_raw`, recording each
        logical block's start position for later reconciliation.

        `keep_focus_on` is an optional (block_index, char_offset) hint for
        where to place the cursor after the rebuild.
        """
        doc = self.editor.document()
        self._render_lock = True
        doc.clear()
        self._register_images(doc)
        cursor = QTextCursor(doc)
        self._block_pos = []
        for i, raw in enumerate(self._block_raw):
            self._block_pos.append(cursor.position())
            if i in self._raw_blocks:
                cursor.insertText(raw)
            else:
                self._render_block(raw, cursor)
            if i != len(self._block_raw) - 1:
                cursor.insertBlock()
        self._doc_len = doc.characterCount()
        self._render_lock = False
        if keep_focus_on is not None:
            self._place_cursor(*keep_focus_on)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.editor.setTextCursor(cursor)

    def _region_bounds(self, idx):
        """(start, end) char positions of logical block `idx`'s region,
        including the separator that ends it (except at document end)."""
        n = len(self._block_raw)
        start = self._block_pos[idx]
        end = self._block_pos[idx + 1] if idx + 1 < n else self._doc_len
        return start, end

    def _region_text(self, start, end):
        # NB: QTextCursor positions max out at characterCount()-1; asking for
        # characterCount() fails and silently resets the cursor to 0 (empty
        # selection), so the last block's region must clamp accordingly. The
        # trailing separator renders as whitespace in the fragment, which the
        # rstrip drops (_split_blocks ignores it anyway).
        doc = self.editor.document()
        end = min(end, doc.characterCount() - 1)
        if end <= start:
            return ""
        c = QTextCursor(doc)
        c.setPosition(max(0, start))
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return c.selection().toPlainText().rstrip()

    def _place_cursor(self, blk_idx, offset):
        if not (0 <= blk_idx < len(self._block_pos)):
            return
        start, end = self._region_bounds(blk_idx)
        span = max(1, end - start)
        pos = start + max(0, min(offset, span - 1))
        c = QTextCursor(self.editor.document())
        c.setPosition(max(0, min(pos, self.editor.document().characterCount() - 1)))
        self.editor.setTextCursor(c)

    def _place_cursor_at(self, pos):
        c = QTextCursor(self.editor.document())
        c.setPosition(max(0, min(pos, self.editor.document().characterCount() - 1)))
        self.editor.setTextCursor(c)

    def _logical_block_at(self, cursor):
        """Index of the logical block containing the cursor."""
        p = cursor.position()
        idx = 0
        for i in range(len(self._block_pos) - 1, -1, -1):
            if self._block_pos[i] <= p:
                return i
        return idx

    # ── edit reconciliation ──────────────────────────────────────────────────
    def _on_contents_change(self, pos, removed, added):
        """Reconcile `_block_raw` with a document edit, using the exact
        change coordinates Qt reports (works for keyboard, context-menu,
        middle-click paste and IME alike).

        Edits confined to a raw block sync directly. Edits crossing block
        boundaries splice every affected block from the document text —
        content the user deleted stays deleted; markdown markers in
        *rendered* blocks the edit crossed are lost, which only happens for
        deliberate multi-block deletes (boundary merges are intercepted
        losslessly instead — see `_WysiwygEdit.keyPressEvent`).
        """
        if self._render_lock:
            return
        n = len(self._block_raw)
        if n == 0 or not self._block_pos:
            self._reconcile_all_from_doc()
            return
        doc = self.editor.document()
        if self._focus is None:
            # Edit before any block was focused (e.g. typing right after a
            # document load): adopt the cursor's block so the edit is
            # reconciled as raw text.
            self._focus = self._logical_block_at(self.editor.textCursor())
            self._raw_blocks.add(self._focus)
        new_len = doc.characterCount()
        old_len = self._doc_len
        delta = new_len - old_len
        chg_start, chg_end = pos, pos + removed

        # Affected logical blocks, in OLD coordinates: any region the change
        # overlaps, plus (for insertions) the block that receives the text.
        affected = []
        for i in range(n):
            s = self._block_pos[i]
            e = self._block_pos[i + 1] if i + 1 < n else old_len
            if s < chg_end and e > chg_start:
                affected.append(i)
        if removed:
            # A removal that lands exactly on a region boundary ate the
            # separator ending the previous region (a Qt block merge): drag
            # the neighbouring block in so the splice covers both sides.
            for k in range(1, n):
                if self._block_pos[k] == chg_end or self._block_pos[k] - 1 == chg_start:
                    if k not in affected:
                        affected.append(k)
        if added:
            k = n - 1
            for i in range(n):
                e = self._block_pos[i + 1] if i + 1 < n else old_len
                if e > pos:
                    k = i
                    break
            if k not in affected:
                affected.append(k)
        if not affected:
            self._reconcile_all_from_doc()
            return

        i0, j0 = min(affected), max(affected)

        if i0 == j0 and i0 in self._raw_blocks:
            # Fast path: the edit is confined to a block shown raw, whose
            # document text IS its markdown.
            self._maybe_push_undo()
            start = self._block_pos[i0]
            end_old = self._block_pos[i0 + 1] if i0 + 1 < n else old_len
            text = self._region_text(start, end_old + delta)
            new_raw = _split_blocks(text)
            if len(new_raw) == 1:
                if self._stream_idx == i0:
                    self._stream_text = new_raw[0]
                self._block_raw[i0] = new_raw[0]
                for k in range(i0 + 1, n):
                    self._block_pos[k] += delta
                self._doc_len = new_len
                self._sync_source()
            else:
                # The block split internally (blank line typed inside it).
                if self._stream_idx == i0:
                    self._stream_idx = i0 + len(new_raw) - 1
                    self._stream_text = new_raw[-1]
                self._block_raw[i0:i0 + 1] = new_raw
                self._sync_source()
                self._place_rebuilt_cursor(i0, pos - start, new_raw)
            return

        # Cross-block edit: splice the whole affected range from the document
        # text. Rendered blocks in the range keep their visible text as the
        # new markdown (markers lost); raw blocks round-trip exactly.
        self._maybe_push_undo(structural=True)
        start = self._block_pos[i0]
        end_old = self._block_pos[j0 + 1] if j0 + 1 < n else old_len
        text = self._region_text(start, end_old + delta)
        if text.strip():
            new_raw = _split_blocks(text)
        elif i0 > 0 or j0 + 1 < n:
            new_raw = []   # the affected blocks vanish entirely
        else:
            new_raw = [""]  # the whole document was deleted
        self._block_raw[i0:j0 + 1] = new_raw
        if not self._block_raw:
            self._block_raw = [""]
        self._sync_source()
        if new_raw:
            self._place_rebuilt_cursor(i0, pos - start, new_raw)
        else:
            # Everything in the range was deleted — park the cursor at the
            # end of the preceding block (or the start of the following one).
            self._focus = max(0, min(i0 - 1, len(self._block_raw) - 1))
            self._raw_blocks = {self._focus}
            if self._stream_idx is not None:
                self._raw_blocks.add(self._stream_idx)
            self._rebuild_view(keep_focus_on=(self._focus, 10 ** 6))

    def _place_rebuilt_cursor(self, i0, rel, new_raw):
        """After a splice, focus the block containing offset `rel` into the
        spliced region and rebuild the view with the cursor nearby."""
        acc = 0
        idx, off = i0, 0
        for k, b in enumerate(new_raw):
            if rel <= acc + len(b):
                idx, off = i0 + k, rel - acc
                break
            acc += len(b) + 2  # blocks rejoin with \n\n in the source
        else:
            idx = i0 + len(new_raw) - 1
            off = len(new_raw[-1])
        self._focus = idx
        self._raw_blocks = {idx}
        if self._stream_idx is not None:
            self._raw_blocks.add(self._stream_idx)
        self._rebuild_view(keep_focus_on=(idx, max(0, off)))

    def _reconcile_all_from_doc(self):
        """Paranoid fallback: the document structure no longer maps onto the
        block list at all. Trust the document wholesale — markers are lost,
        but nothing the user deleted can ever resurrect."""
        self._maybe_push_undo(structural=True)
        self._block_raw = _split_blocks(self.editor.document().toPlainText()) or [""]
        self._focus = None
        self._raw_blocks = set()
        if self._stream_idx is not None:
            self._raw_blocks.add(self._stream_idx)
        self._sync_source()
        self._rebuild_view()

    def _on_cursor_moved(self):
        if self._render_lock:
            return
        cur = self.editor.textCursor()
        if cur.hasSelection():
            # Keep focus pinned while a selection is active: rebuilding
            # mid-drag would destroy the selection (and cross-block deletes
            # are reconciled from contentsChange anyway).
            return
        idx = self._logical_block_at(cur)
        if idx == self._focus:
            return
        offset = cur.position() - self._block_pos[idx]
        self._focus = idx
        self._raw_blocks = {idx}
        if self._stream_idx is not None:
            self._raw_blocks.add(self._stream_idx)
        self._rebuild_view(keep_focus_on=(idx, offset))

    # ── boundary merges (lossless) ───────────────────────────────────────────
    def _at_region_start(self, cur):
        """Cursor sits before the first char of the focused block and there
        is a block before it — Backspace would merge across the boundary."""
        if self._focus is None or self._focus <= 0 or not self._block_pos:
            return False
        return cur.position() == self._block_pos[self._focus]

    def _at_region_end(self, cur):
        """Cursor sits after the last char of the focused block and there is
        a block after it — Delete would merge across the boundary."""
        if self._focus is None or self._focus >= len(self._block_raw) - 1:
            return False
        start, end = self._region_bounds(self._focus)
        return cur.position() == end - 1

    def _merge_with_prev(self):
        """Backspace at block start: merge this block's markdown onto the
        previous block's markdown (no marker loss), cursor at the junction."""
        i = self._focus
        if i is None or i <= 0:
            return
        self._maybe_push_undo(structural=True)
        prev = self._block_raw[i - 1]
        merged = prev + self._block_raw[i]
        self._block_raw[i - 1:i + 1] = [merged]
        self._focus = i - 1
        self._raw_blocks = {i - 1}
        if self._stream_idx is not None:
            self._raw_blocks.add(self._stream_idx)
        self._sync_source()
        self._rebuild_view(keep_focus_on=(i - 1, len(prev)))

    def _merge_with_next(self):
        """Delete at block end: merge the next block's markdown onto this
        one (no marker loss), cursor stays at the junction."""
        i = self._focus
        if i is None or i >= len(self._block_raw) - 1:
            return
        self._maybe_push_undo(structural=True)
        cur_txt = self._block_raw[i]
        merged = cur_txt + self._block_raw[i + 1]
        self._block_raw[i:i + 2] = [merged]
        self._focus = i
        self._raw_blocks = {i}
        if self._stream_idx is not None:
            self._raw_blocks.add(self._stream_idx)
        self._sync_source()
        self._rebuild_view(keep_focus_on=(i, len(cur_txt)))

    # ── undo / redo over block snapshots ────────────────────────────────────
    def _maybe_push_undo(self, structural=False):
        """Snapshot the pre-edit state. Consecutive fast edits in the same
        block within the coalesce window collapse into one undo step."""
        if self._stream_idx is not None:
            return  # the whole streamed answer is one undo step (stream_start)
        now = time.monotonic()
        if (not structural and self._undo_stack
                and self._undo_last_focus == self._focus
                and now - self._undo_last_t < self.UNDO_COALESCE_S):
            self._undo_last_t = now
            return
        cur = self.editor.textCursor()
        idx = self._logical_block_at(cur) if self._block_pos else 0
        off = cur.position() - self._block_pos[idx] if self._block_pos else 0
        self._undo_stack.append((list(self._block_raw), self._focus, (idx, off)))
        if len(self._undo_stack) > self.UNDO_STACK_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._undo_last_t = now
        self._undo_last_focus = self._focus

    def _undo(self):
        if not self._undo_stack or self._stream_idx is not None:
            return
        snap = self._undo_stack.pop()
        self._redo_stack.append(self._current_snapshot())
        self._apply_snapshot(snap)

    def _redo(self):
        if not self._redo_stack or self._stream_idx is not None:
            return
        snap = self._redo_stack.pop()
        self._undo_stack.append(self._current_snapshot())
        self._apply_snapshot(snap)

    def _current_snapshot(self):
        cur = self.editor.textCursor()
        idx = self._logical_block_at(cur) if self._block_pos else 0
        off = cur.position() - self._block_pos[idx] if self._block_pos else 0
        return (list(self._block_raw), self._focus, (idx, off))

    def _apply_snapshot(self, snap):
        raw, focus, (idx, off) = snap
        self._block_raw = list(raw)
        self._focus = None
        self._raw_blocks = set()
        self._sync_source()
        self._rebuild_view(keep_focus_on=(min(idx, len(self._block_raw) - 1), off))

    # ── programmatic append / AI streaming ─────────────────────────────────
    def append_markdown(self, block):
        """Append a markdown block (highlight / capture / caption) without
        yanking the user's cursor away."""
        self._append_blocks([block])

    def _append_blocks(self, blocks):
        if not blocks:
            return
        self._maybe_push_undo(structural=True)
        save_cur = None
        if self._focus is not None and self._block_pos:
            cur = self.editor.textCursor()
            idx = self._logical_block_at(cur)
            save_cur = (idx, cur.position() - self._block_pos[idx])
        for b in blocks:
            if b.strip():
                self._block_raw.append(b.rstrip())
        self._source = self._normalize("\n\n".join(self._block_raw))
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._sync_source()
        self._rebuild_view(keep_focus_on=save_cur)
        self._flush_save()

    def stream_start(self, heading):
        self._append_blocks([heading])
        self._stream_idx = len(self._block_raw) - 1
        self._stream_text = self._block_raw[self._stream_idx]
        self._stream_buffer = ""
        self._focus = self._stream_idx
        self._raw_blocks = {self._stream_idx}
        self._rebuild_view(keep_focus_on=(self._stream_idx, len(self._stream_text)))

    def stream_token(self, tok):
        if self._stream_idx is None:
            return
        self._stream_text += tok
        self._stream_buffer += tok
        if not self._flush.isActive():
            self._flush.start()

    def _drain(self):
        if self._stream_idx is None or not self._stream_buffer:
            self._flush.stop()
            return
        self._stream_buffer = ""
        self._update_stream_region()

    def _update_stream_region(self):
        """Rewrite only the streaming block's region in the live document —
        rendered blocks are untouched (no flicker) and the user's cursor
        outside the region is preserved."""
        idx = self._stream_idx
        doc = self.editor.document()
        start, end = self._region_bounds(idx)
        text = self._stream_text
        user_pos = self.editor.textCursor().position()
        self._render_lock = True
        c = QTextCursor(doc)
        c.setPosition(start)
        # Same clamp as _region_text: positions top out at characterCount()-1.
        c.setPosition(min(end, doc.characterCount() - 1),
                      QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()
        c.insertText(text)
        self._render_lock = False
        new_len = doc.characterCount()
        delta = new_len - self._doc_len
        self._block_raw[idx] = text
        n = len(self._block_raw)
        for k in range(idx + 1, n):
            self._block_pos[k] += delta
        self._doc_len = new_len
        if start <= user_pos <= end:
            self._place_cursor(idx, len(text))
        elif user_pos > end:
            self._place_cursor_at(user_pos + delta)
        else:
            self._place_cursor_at(user_pos)
        self._sync_source()

    def stream_end(self):
        self._flush.stop()
        if self._stream_idx is not None:
            text = self._stream_text.rstrip()
            if text:
                self._block_raw[self._stream_idx] = text
            else:
                del self._block_raw[self._stream_idx]
            self._stream_idx = None
            self._stream_text = ""
            self._stream_buffer = ""
        self._source = self._normalize("\n\n".join(self._block_raw))
        self._block_raw = _split_blocks(self._source)
        if not self._block_raw:
            self._block_raw = [""]
        self._focus = None
        self._raw_blocks = set()
        self._rebuild_view()
        self._flush_save()

    # ── PDF export ──────────────────────────────────────────────────────────
    def export_pdf(self):
        """Export the notes (plus the whiteboard section, D1) to a PDF.

        The document is *self-paginated*: the QPdfWriter is installed as the
        layout's paint device and the page size is set to the writer's
        printable rect, so `QTextDocument.print()` takes its already-
        paginated branch and reproduces our layout 1:1 — no hidden 2 cm
        frame margins computed from screen DPI, no hardcoded page-number
        footer, and text wraps exactly inside the margins (E8). The file is
        written to a sibling temp file and atomically renamed over the
        target, so re-exporting over an existing file always works and a
        locked/unwritable target surfaces as a dialog instead of silence.
        """
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Notes as PDF", "notes.pdf", "PDF Files (*.pdf)")
        if not path:
            return
        # Flush any pending edit so the exported doc matches the live source.
        self._save_timer.stop()
        self._flush_save()
        source = self._source
        if self._export_extra:
            extra = self._export_extra()
            if extra:
                source = source.rstrip() + "\n\n" + extra
        html = render_markdown_html(self._resolve_full(source))
        # Belt-and-braces line wrapping for code blocks: Qt honours
        # `white-space: pre-wrap` most reliably as an inline attribute.
        html = html.replace("<pre>", '<pre style="white-space: pre-wrap">')

        doc = QTextDocument()
        doc.setDefaultFont(QFont(EXPORT_FONT_FAMILY, 11))
        _to = QTextOption()
        _to.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(_to)
        doc.setDocumentMargin(0)
        if self._base_dir:
            for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', source):
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

        tmp_path = path + ".tmp"
        try:
            writer = QPdfWriter(tmp_path)
            writer.setResolution(96)  # device px == layout px: images keep their size
            writer.setCreator("Pyxis")
            writer.setTitle(Path(self._base_dir or ".").name + " — notes"
                            if self._base_dir else "Pyxis notes")
            writer.setPageLayout(QPageLayout(
                QPageSize(QPageSize.PageSizeId.A4),
                QPageLayout.Orientation.Portrait,
                QMarginsF(EXPORT_MARGINS_MM, EXPORT_MARGINS_MM,
                          EXPORT_MARGINS_MM, EXPORT_MARGINS_MM),
                QPageLayout.Unit.Millimeter))
            doc.documentLayout().setPaintDevice(writer)
            doc.setPageSize(QSizeF(writer.width(), writer.height()))
            doc.setHtml(_export_html(html))
            doc.print(writer)
            # Drop the C++ object so the temp file is closed before rename.
            del writer
            gc.collect()
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise RuntimeError("the PDF writer produced no output")
            os.replace(tmp_path, path)
            QMessageBox.information(self, "Export", f"Notes exported to\n{path}")
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            QMessageBox.warning(
                self, "Export failed",
                f"Could not write {path}:\n{e}\n\n"
                f"If the file is open in another program, close it and try again.")

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
