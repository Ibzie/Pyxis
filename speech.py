"""Text-to-speech backends and a sentence-grained playback queue.

Primary backend: Piper (neural, ~65 MB voice file, fully offline).
Fallback: pyttsx3 (eSpeak, robotic but zero ML deps) — auto-detected at
import time. The SpeechQueue runs on a QThread so the UI never blocks;
it emits `chunk_started(str)` before speaking each sentence and
`chunk_done()` after, so callers can highlight words or track progress.
"""

import re
import queue
import logging
from pathlib import Path

log = logging.getLogger("speech")

VOICE_CACHE_DIR = Path.home() / ".local" / "share" / "pyxis" / "voices"
VOICE_REPO = "rhasspy/piper-voices"
VOICE_PATH = "en/en_US/lessac/medium"
VOICE_MODEL = "en_US-lessac-medium.onnx"
VOICE_CONFIG = "en_US-lessac-medium.onnx.json"

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text):
    """Split text into speakable chunks. Merges very short fragments and
    breaks very long sentences at commas so Piper gets natural-sized chunks."""
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    chunks = []
    buf = ""
    for p in parts:
        if len(p) > 200:
            if buf:
                chunks.append(buf)
                buf = ""
            for sub in re.split(r"([,;])\s+", p):
                if sub in (",", ";"):
                    continue
                if buf and len(buf) + len(sub) > 200:
                    chunks.append(buf.rstrip(",;"))
                    buf = sub
                else:
                    buf = (buf + " " + sub).strip() if buf else sub
        elif len(buf) + len(p) < 40:
            buf = (buf + " " + p).strip() if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks


class PiperEngine:
    """Piper neural TTS — primary backend."""

    def __init__(self, on_status=None):
        self._voice = None
        self._sample_rate = 22050
        self._cancel = False
        self._speaking = False
        self._load_voice(on_status)

    def _load_voice(self, on_status):
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice
        VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if on_status:
            on_status("Downloading TTS voice (first run only, ~65 MB)…")
        model_path = hf_hub_download(
            repo_id=VOICE_REPO, filename=f"{VOICE_PATH}/{VOICE_MODEL}",
            cache_dir=str(VOICE_CACHE_DIR.parent),
        )
        config_path = hf_hub_download(
            repo_id=VOICE_REPO, filename=f"{VOICE_PATH}/{VOICE_CONFIG}",
            cache_dir=str(VOICE_CACHE_DIR.parent),
        )
        if on_status:
            on_status("Loading TTS voice…")
        self._voice = PiperVoice.load(model_path, config_path=config_path)
        self._sample_rate = self._voice.config.sample_rate
        log.info("piper voice loaded: %s, sr=%d", VOICE_MODEL, self._sample_rate)

    def speak(self, text):
        import numpy as np
        import sounddevice as sd
        if not text.strip():
            return
        self._cancel = False
        self._speaking = True
        try:
            chunks = list(self._voice.synthesize(text))
            if not chunks or self._cancel:
                return
            audio = np.concatenate([
                np.frombuffer(c.audio_int16_bytes, dtype=np.int16) for c in chunks
            ])
            if self._cancel or len(audio) == 0:
                return
            sd.play(audio, self._sample_rate)
            sd.wait()
        except Exception as e:
            log.warning("speak failed: %s", e)
        finally:
            self._speaking = False

    def cancel(self):
        self._cancel = True
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def is_speaking(self):
        return self._speaking

    def shutdown(self):
        self.cancel()
        if self._voice is not None:
            try:
                del self._voice
            except Exception:
                pass
        self._voice = None


class Pyttsx3Engine:
    """eSpeak-based fallback — robotic but zero ML deps."""

    def __init__(self, on_status=None):
        import pyttsx3
        if on_status:
            on_status("Loading TTS (pyttsx3 fallback)…")
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", 180)

    def speak(self, text):
        if not text.strip():
            return
        self._engine.say(text)
        self._engine.runAndWait()

    def cancel(self):
        try:
            self._engine.stop()
        except Exception:
            pass

    def is_speaking(self):
        return False

    def shutdown(self):
        self.cancel()


def create_engine(on_status=None):
    """Try Piper first; fall back to pyttsx3 if Piper unavailable."""
    try:
        return PiperEngine(on_status)
    except Exception as e:
        log.warning("piper unavailable, falling back to pyttsx3: %s", e)
        if on_status:
            on_status(f"Piper unavailable ({e}); using pyttsx3 fallback")
        try:
            return Pyttsx3Engine(on_status)
        except Exception as e2:
            log.error("pyttsx3 also unavailable: %s", e2)
            raise RuntimeError(f"No TTS backend available: piper={e}, pyttsx3={e2}")


from PyQt6.QtCore import QThread, pyqtSignal


class SpeechQueue(QThread):
    """Background thread that speaks enqueued text chunks sequentially.

    Signals:
        chunk_started(str)  — fired before each chunk is spoken
        chunk_done()        — fired after each chunk finishes
        queue_empty()       — fired when the queue drains completely
        failed(str)         — fired on engine errors
    """

    chunk_started = pyqtSignal(str)
    chunk_done = pyqtSignal()
    queue_empty = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._queue = queue.Queue()
        self._running = True

    def enqueue(self, text):
        """Add text to the speak queue. Splits into sentence-grained chunks."""
        for chunk in split_sentences(text):
            self._queue.put(chunk)

    def cancel(self):
        """Clear the queue and stop current playback immediately."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._engine.cancel()

    def run(self):
        while self._running:
            try:
                text = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if text is None:
                break
            self.chunk_started.emit(text)
            self._engine.speak(text)
            self.chunk_done.emit()
        self.queue_empty.emit()

    def stop(self):
        """Stop the thread, cancel playback, and wait for exit."""
        self._running = False
        self._queue.put(None)
        self._engine.cancel()
        self.wait(3000)

    @property
    def pending(self):
        return self._queue.qsize()
