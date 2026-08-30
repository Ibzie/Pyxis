import json
import os
import sys
import contextlib
from pathlib import Path
from datetime import datetime
import zlib

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


def app_data_dir():
    """OS-specific writable data directory for Pyxis.

    Linux:  ~/.local/share/pyxis/
    macOS:  ~/Library/Application Support/pyxis/
    Windows: %APPDATA%\\pyxis\\
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "pyxis"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "pyxis"
    else:
        return Path.home() / ".local" / "share" / "pyxis"


# A7: one-time a11y onboarding flag — the Accessibility Help is read aloud
# the first time accessibility mode is ever enabled, so blind users discover
# the shortcuts without a screen reader.
_A11Y_ONBOARDED = "a11y_onboarded"


def a11y_onboarded():
    return (app_data_dir() / _A11Y_ONBOARDED).exists()


def mark_a11y_onboarded():
    d = app_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / _A11Y_ONBOARDED).write_text("1")


def load_settings():
    """Load the global UI settings dict (A11: font scale / high contrast)."""
    p = app_data_dir() / "settings.json"
    try:
        if p.exists():
            data = json.loads(p.read_text())
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_settings(settings):
    """Persist the global UI settings dict atomically."""
    d = app_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "settings.json"
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


class PdfStorage:
    BASE_DIR = app_data_dir() / "notes"

    def __init__(self, pdf_path):
        self.pdf_path = Path(pdf_path)
        self.folder = self._resolve_folder()
        self.highlights_dir = self.folder / "highlights"
        self.captures_dir = self.folder / "captures"
        self.notes_file = self.folder / "notes.md"
        self.annotations_file = self.folder / "annotations.json"
        self.whiteboard_file = self.folder / "whiteboard.png"
        self._ensure_dirs()
        self.annotations = self._load_json(
            self.annotations_file,
            {"highlights": [], "captures": [], "image_descriptions": {}},
        )
        if "image_descriptions" not in self.annotations:
            self.annotations["image_descriptions"] = {}
        # Record which file owns this folder so a future name collision (G2)
        # can be detected and disambiguated instead of leaking notes between
        # distinct documents ("a b.pdf" vs "a_b.pdf" both sanitize to "a_b").
        if "pdf_name" not in self.annotations:
            self.annotations["pdf_name"] = self.pdf_path.name
            self._save_json(self.annotations_file, self.annotations)

    def _safe_name(self, name):
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)

    def _resolve_folder(self):
        """Pick the notes folder for this PDF, disambiguating collisions.

        Sanitizing the filename is lossy ("a b.pdf" and "a_b.pdf" both map to
        "a_b"), so a folder that already exists is only reused when its
        recorded `pdf_name` matches ours. Legacy folders with no record are
        reused as before; new colliding names get a stable suffix."""
        base = self.BASE_DIR / self._safe_name(self.pdf_path.stem)
        if not base.exists():
            return base
        ann = self._load_json(base / "annotations.json", None)
        owner = (ann or {}).get("pdf_name")
        if owner is None or owner == self.pdf_path.name:
            return base
        # Collision: this folder belongs to another document. Find a distinct,
        # deterministic name so both documents keep separate notes forever.
        stem = self._safe_name(self.pdf_path.stem)
        for n in range(1, 100):
            tag = zlib.crc32(f"{self.pdf_path.name}{n}".encode("utf-8")) & 0xFFFF
            candidate = self.BASE_DIR / f"{stem}-{tag:04x}"
            if not candidate.exists():
                return candidate
            ann2 = self._load_json(candidate / "annotations.json", None)
            if (ann2 or {}).get("pdf_name") == self.pdf_path.name:
                return candidate
        return self.BASE_DIR / f"{stem}-{self.pdf_path.name}"

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
        # Atomic write (G4): temp file + fsync + os.replace, mirroring
        # save_notes() — a crash mid-write must never truncate the file.
        # Also re-reads the disk state and merges under a cross-process lock
        # (G3) so a save from one instance never clobbers entries another
        # instance wrote after we loaded.
        with self._file_lock():
            merged = self._merge_json(path, data)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w") as f:
                json.dump(merged, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)

    @contextlib.contextmanager
    def _file_lock(self):
        """Serialize concurrent writers to this PDF's folder across processes
        (G3). Atomic replace already prevents truncation; the lock prevents two
        writers from interleaving their read-modify-write cycles."""
        lock_path = self.folder / ".lock"
        fh = open(lock_path, "a+")
        try:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            elif msvcrt:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            try:
                if fcntl:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                elif msvcrt:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            fh.close()

    def _merge_json(self, path, data):
        """Re-read the file on disk and merge before overwriting (G3):
        dict-typed state merges key-by-key (per-key last-write-wins), list-
        typed state is unioned by identity so another instance's additions
        survive this save."""
        try:
            disk = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            return data
        if not isinstance(disk, dict) or not disk:
            return data
        out = dict(data)
        # image_descriptions: union, per-key last-write-wins.
        d_img = dict(disk.get("image_descriptions") or {})
        d_img.update(data.get("image_descriptions") or {})
        out["image_descriptions"] = d_img
        # narration_position: newest timestamp wins.
        dts = str((disk.get("narration_position") or {}).get("timestamp", ""))
        mts = str((data.get("narration_position") or {}).get("timestamp", ""))
        if mts >= dts:
            out["narration_position"] = data.get("narration_position")
        else:
            out["narration_position"] = disk.get("narration_position")
        # highlights/captures: union by stable identity.
        for k in ("highlights", "captures"):
            mine = list(data.get(k) or [])
            theirs = disk.get(k) or []
            seen = {self._entry_key(e) for e in mine}
            for e in theirs:
                key = self._entry_key(e)
                if key not in seen:
                    mine.append(e)
                    seen.add(key)
            out[k] = mine
        return out

    @staticmethod
    def _entry_key(e):
        if not isinstance(e, dict):
            return repr(e)
        if "file" in e:
            return (e.get("type"), e.get("page"), e.get("file"))
        return (e.get("type"), e.get("page"), tuple(e.get("bbox", ())))

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
        """Write notes.md atomically (B6): a crash or power loss mid-write
        must never leave a truncated/corrupt file — write to a sibling temp
        file, fsync it, then atomically replace the target. The cross-process
        lock (G3) serializes concurrent writers."""
        with self._file_lock():
            tmp = self.notes_file.with_suffix(self.notes_file.suffix + ".tmp")
            with open(tmp, "w") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.notes_file)

    def save_whiteboard(self, pixmap):
        """Persist the per-PDF whiteboard as a flattened PNG (D1), matching
        the highlights/captures convention."""
        if pixmap is not None and not pixmap.isNull():
            pixmap.save(str(self.whiteboard_file))

    def load_whiteboard(self):
        """Return the saved whiteboard QPixmap, or None."""
        if self.whiteboard_file.exists():
            from PyQt6.QtGui import QPixmap
            pix = QPixmap(str(self.whiteboard_file))
            if not pix.isNull():
                return pix
        return None

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

    # ── narration resume position (accessibility) ──────────────────────────
    def get_narration_position(self):
        """Return the last-saved narration position, or None.

        Shape: {"page": int, "chunk": int, "timestamp": str}
        """
        return self.annotations.get("narration_position")

    def save_narration_position(self, page, chunk):
        """Persist the current narration position so the user can resume
        after closing/reopening the PDF. `chunk` is an index into the
        page's RAG chunk list (0 = start of page)."""
        self.annotations["narration_position"] = {
            "page": int(page),
            "chunk": int(chunk),
            "timestamp": self._now_iso(),
        }
        self._save_json(self.annotations_file, self.annotations)
