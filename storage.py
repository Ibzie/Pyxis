import json
import os
import sys
from pathlib import Path
from datetime import datetime


def app_data_dir():
    """OS-specific writable data directory for AI-PDF.

    Linux:  ~/.local/share/ai-pdf/
    macOS:  ~/Library/Application Support/ai-pdf/
    Windows: %APPDATA%\\ai-pdf\\
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ai-pdf"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "ai-pdf"
    else:
        return Path.home() / ".local" / "share" / "ai-pdf"


class PdfStorage:
    BASE_DIR = app_data_dir() / "notes"

    def __init__(self, pdf_path):
        self.pdf_path = Path(pdf_path)
        self.folder = self.BASE_DIR / self._safe_name(self.pdf_path.stem)
        self.highlights_dir = self.folder / "highlights"
        self.captures_dir = self.folder / "captures"
        self.notes_file = self.folder / "notes.md"
        self.annotations_file = self.folder / "annotations.json"
        self._ensure_dirs()
        self.annotations = self._load_json(
            self.annotations_file,
            {"highlights": [], "captures": [], "image_descriptions": {}},
        )
        if "image_descriptions" not in self.annotations:
            self.annotations["image_descriptions"] = {}

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

    def save_rag_image(self, page_idx, img):
        filename = f"rag_p{page_idx}_{self._timestamp()}.png"
        filepath = self.captures_dir / filename
        img.save(str(filepath))
        return filepath

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

    # ── image descriptions (accessibility) ─────────────────────────────────
    def _img_key(self, page_idx, bbox):
        return f"{page_idx}_{tuple(round(v, 1) for v in bbox)}"

    def get_image_description(self, page_idx, bbox):
        """Return cached description for an image region, or None."""
        return self.annotations.get("image_descriptions", {}).get(
            self._img_key(page_idx, bbox))

    def save_image_description(self, page_idx, bbox, description, img_path=None):
        """Cache an AI-generated image description so we skip the model on
        subsequent openings of the same PDF."""
        key = self._img_key(page_idx, bbox)
        entry = {"description": description, "timestamp": self._now_iso()}
        if img_path:
            entry["file"] = str(Path(img_path).relative_to(self.folder))
        self.annotations.setdefault("image_descriptions", {})[key] = entry
        self._save_json(self.annotations_file, self.annotations)
