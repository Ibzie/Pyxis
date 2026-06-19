import json
from pathlib import Path
from datetime import datetime


class PdfStorage:
    BASE_DIR = Path("notes")

    def __init__(self, pdf_path):
        self.pdf_path = Path(pdf_path)
        self.folder = self.BASE_DIR / self._safe_name(self.pdf_path.stem)
        self.highlights_dir = self.folder / "highlights"
        self.captures_dir = self.folder / "captures"
        self.notes_file = self.folder / "notes.md"
        self.annotations_file = self.folder / "annotations.json"
        self._ensure_dirs()
        self.annotations = self._load_json(self.annotations_file, {"highlights": [], "captures": []})

    def _safe_name(self, name):
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)

    def _ensure_dirs(self):
        self.highlights_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def _load_json(self, path, default):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return default

    def _save_json(self, path, data):
        path.write_text(json.dumps(data, indent=2))

    def _timestamp(self):
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _now_iso(self):
        return datetime.now().isoformat()

    def save_highlight(self, page_idx, img, bbox, text):
        filename = f"hl_p{page_idx}_{self._timestamp()}.png"
        filepath = self.highlights_dir / filename
        img.save(str(filepath))
        entry = {
            "type": "highlight",
            "page": page_idx,
            "file": str(filepath.relative_to(self.folder)),
            "bbox": list(bbox),
            "text": text,
            "timestamp": self._now_iso(),
        }
        self.annotations["highlights"].append(entry)
        self._save_json(self.annotations_file, self.annotations)
        return filepath, entry

    def save_capture(self, page_idx, img):
        filename = f"cap_p{page_idx}_{self._timestamp()}.png"
        filepath = self.captures_dir / filename
        img.save(str(filepath))
        entry = {
            "type": "capture",
            "page": page_idx,
            "file": str(filepath.relative_to(self.folder)),
            "timestamp": self._now_iso(),
        }
        self.annotations["captures"].append(entry)
        self._save_json(self.annotations_file, self.annotations)
        return filepath, entry

    def load_notes(self):
        if self.notes_file.exists():
            return self.notes_file.read_text()
        return f"# Notes: {self.pdf_path.name}\n\n"

    def save_notes(self, text):
        self.notes_file.write_text(text)

    def get_highlights_for_page(self, page_idx):
        return [h for h in self.annotations["highlights"] if h["page"] == page_idx]

    def remove_highlight(self, page_idx, hl_idx):
        kept = []
        count = 0
        for h in self.annotations["highlights"]:
            if h["page"] == page_idx:
                if count != hl_idx:
                    kept.append(h)
                count += 1
            else:
                kept.append(h)
        self.annotations["highlights"] = kept
        self._save_json(self.annotations_file, self.annotations)
