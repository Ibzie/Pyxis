import re
from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz


def tokenize(text):
    return re.findall(r'\b\w+\b', text.lower())


class RagIndex:
    """Sparse retrieval index over a single PDF's paragraphs, tables, and images."""

    def __init__(self):
        self.chunks = []
        self.page_texts = []
        self.bm25 = None
        self._ready = False

    @property
    def is_ready(self):
        return self._ready

    # ── indexing (call from a worker thread) ────────────────────────────────
    def index_page(self, page, page_idx):
        import fitz
        self.page_texts.append(page.get_text())
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") == 0:
                text = self._block_text(block)
                if len(text.strip()) > 10:
                    self._add(page_idx, "para", text)
            elif block.get("type") == 1:
                rect = block["bbox"]
                nearby = self._nearby_text(page, rect)
                embedded = page.get_textbox(fitz.Rect(rect)).strip()
                text = f"{nearby} {embedded}".strip()
                self._add(page_idx, "image", text or "[no text near image]",
                          image_rect=tuple(rect))
        try:
            for tab in page.find_tables().tables:
                rows = tab.extract()
                md = self._rows_to_md(rows)
                if md:
                    self._add(page_idx, "table", md)
        except Exception:
            pass

    def finalize(self):
        corpus = [tokenize(c["text"]) for c in self.chunks]
        if corpus:
            self.bm25 = BM25Okapi(corpus)
        self._ready = True

    # ── retrieval ───────────────────────────────────────────────────────────
    def retrieve(self, expanded_query, top_k=6):
        if not self.bm25:
            return []
        tokens = tokenize(expanded_query)
        scores = self.bm25.get_scores(tokens)
        candidates = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 3]
        # Blend BM25 (normalized) with fuzzy surface similarity so keyword
        # matching dominates while fuzzy catches word-form variants.
        max_bm = max((scores[i] for i in candidates), default=1) or 1
        def blend(i):
            bm = scores[i] / max_bm
            fz = fuzz.token_sort_ratio(
                expanded_query.lower(), self.chunks[i]["text"][:300].lower()) / 100
            return 0.65 * bm + 0.35 * fz
        reranked = sorted(candidates, key=blend, reverse=True)
        return [self.chunks[i] for i in reranked[:top_k]]

    def assemble_context(self, chunks, budget=12000):
        parts, total, images, pages = [], 0, [], set()
        for c in chunks:
            tag = f"[Page {c['page']+1}"
            if c["type"] == "table":
                tag += ", Table]"
            elif c["type"] == "image":
                tag += ", Figure]"
                images.append(c)
            else:
                tag += ", paragraph]"
            text = c["text"][:budget // 4]
            block = f"{tag}\n{text}"
            if total + len(block) > budget:
                break
            parts.append(block)
            total += len(block)
            pages.add(c["page"])
        if pages and budget - total > 500:
            top_page = sorted(pages)[0]
            full = self.page_texts[top_page]
            if len(full) > budget - total:
                full = full[:budget - total] + " [...]"
            parts.append(f"[Page {top_page+1} — full page text]\n{full}")
        return "\n\n---\n\n".join(parts), images

    # ── helpers ──────────────────────────────────────────────────────────────
    def _add(self, page_idx, typ, text, **extra):
        chunk = {"page": page_idx, "type": typ, "text": text}
        chunk.update(extra)
        self.chunks.append(chunk)

    @staticmethod
    def _block_text(block):
        lines = []
        for line in block.get("lines", []):
            lines.append(" ".join(s.get("text", "") for s in line.get("spans", [])))
        return " ".join(lines).strip()

    @staticmethod
    def _nearby_text(page, rect, dist=50):
        x0, y0, x1, y1 = rect
        out = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            bx0, by0, bx1, by1 = block["bbox"]
            if bx1 < x0 or bx0 > x1:
                continue
            if abs(by1 - y0) < dist or abs(by0 - y1) < dist:
                t = RagIndex._block_text(block)
                if t:
                    out.append(t)
        return " ".join(out)

    @staticmethod
    def _rows_to_md(rows):
        if not rows or len(rows) < 2:
            return ""
        if len(rows) > 10:
            rows = rows[:10]
            rows.append(["... (table continues)"])
        header = "| " + " | ".join(str(c or "") for c in rows[0]) + " |"
        sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
        body = ["| " + " | ".join(str(c or "") for c in r) + " |" for r in rows[1:]]
        return "\n".join([header, sep] + body)