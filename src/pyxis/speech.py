"""Text-to-speech backends and the render-then-play narration player (E9).

Primary backend: Piper (neural, ~65 MB voice file, fully offline).
Fallback: pyttsx3 (eSpeak, robotic but zero ML deps) — auto-detected at
import time. Both engines *render* text to PCM (`render_pcm`) / WAV
(`render_wav`); they never touch the audio device themselves.

`NarrationPlayer` owns playback: the narrator renderer synthesizes each
sentence chunk off-thread and appends it to the player's PCM timeline;
the player thread walks that timeline and writes small blocks to the
audio device. Pause/resume is a frame pointer — sample-accurate, and
rendering keeps buffering ahead while paused so resume is instant. This
replaces the old speak-queue design, where pause had to cancel in-flight
synthesis and re-stash sentences (a nest of races: dropped cancels,
double-replayed sentences, and R/C landing on a still-paused queue).

Bookmarks are exact: each appended chunk records its (page, chunk) tag,
and the timeline's frame offsets are prefix sums, so `position_changed`
and cross-session resume map between audio frames and document positions
without guessing.
"""

import re
import os
import wave
import time
import logging
import threading
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

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


# Piper's SynthesisConfig exposes length_scale (inverse of speed) and volume.
# Guard the import so older piper builds still work (volume then becomes a
# manual int16 scale in render_wav).
try:
    from piper import SynthesisConfig as _SynthesisConfig
    _HAS_SYNTH_CONFIG = True
except Exception:
    _HAS_SYNTH_CONFIG = False


class PiperEngine:
    """Piper neural TTS — primary backend (synthesis only, no playback)."""

    def __init__(self, on_status=None):
        self._voice = None
        self._sample_rate = 22050
        self._volume = 1.0          # 0.0–1.0 (applied in render_wav)
        self._length_scale = 1.0    # >1 slows down; 1.0 = native speed
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

    def set_rate(self, speed):
        """speed is a multiplier (0.5 = half speed, 2.0 = double)."""
        speed = max(0.25, min(speed, 4.0))
        self._length_scale = 1.0 / speed

    def set_volume(self, v):
        self._volume = max(0.0, min(v, 1.0))

    def _synthesize(self, text, volume):
        if _HAS_SYNTH_CONFIG:
            cfg = _SynthesisConfig(length_scale=self._length_scale, volume=volume)
            return list(self._voice.synthesize(text, cfg))
        return list(self._voice.synthesize(text))

    def render_pcm(self, text):
        """Synthesize `text` to mono int16 PCM: (ndarray, sample_rate), or
        None for empty input. Volume is NOT baked in — the player applies it
        live so the slider takes effect on the block currently playing."""
        if not text.strip() or self._voice is None:
            return None
        import numpy as np
        chunks = self._synthesize(text, 1.0)
        if not chunks:
            return None
        audio = np.concatenate([
            np.frombuffer(c.audio_int16_bytes, dtype=np.int16) for c in chunks
        ])
        if len(audio) == 0:
            return None
        return audio, self._sample_rate

    def render_wav(self, text, path):
        """Synthesize `text` to a WAV file (A10). The frames Piper already
        produces per sentence are written straight to a wave file, so exports
        match exactly what live playback sounds like."""
        if not self._voice:
            raise RuntimeError("No TTS voice loaded")
        if not text.strip():
            raise RuntimeError("Nothing to render")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            chunks = self._synthesize(text, self._volume)
            for c in chunks:
                wf.writeframes(c.audio_int16_bytes)
        return path

    def shutdown(self):
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
        self._engine.setProperty("volume", 1.0)
        self._rate_mult = 1.0

    def set_rate(self, speed):
        speed = max(0.25, min(speed, 4.0))
        self._rate_mult = speed
        self._engine.setProperty("rate", int(180 * speed))

    def set_volume(self, v):
        self._engine.setProperty("volume", max(0.0, min(v, 1.0)))

    def render_pcm(self, text):
        """Render offline via pyttsx3's save_to_file, then read the WAV back
        as mono int16 PCM (E9 — playback lives in NarrationPlayer)."""
        if not text.strip():
            return None
        import tempfile
        import numpy as np
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._engine.save_to_file(text, path)
            self._engine.runAndWait()
            with wave.open(path, "rb") as wf:
                sr = wf.getframerate()
                chans = wf.getnchannels()
                raw = wf.readframes(wf.getnframes())
            data = np.frombuffer(raw, dtype=np.int16)
            if chans == 2:
                data = data[::2]
            if len(data) == 0:
                return None
            return data, sr
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def render_wav(self, text, path):
        rendered = self.render_pcm(text)
        if rendered is None:
            raise RuntimeError("Nothing to render")
        data, sr = rendered
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(data.tobytes())
        return path

    def shutdown(self):
        try:
            self._engine.stop()
        except Exception:
            pass


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


class VoiceLoadWorker(QThread):
    """Load the (possibly first-run) TTS engine off the GUI thread.

    Piper's voice download (~65 MB) blocks for tens of seconds on a fresh
    machine; doing that on the GUI thread freezes the whole window (A9).
    Mirrors the AI layer's LoadWorker: emit `status` during download, then
    hand the constructed engine back via `done`, or `failed` on error.
    """
    status = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            engine = create_engine(on_status=lambda m: self.status.emit(m))
            self.done.emit(engine)
        except Exception as e:
            log.error("voice load failed: %s", e)
            self.failed.emit(str(e))


class WavExportWorker(QThread):
    """Render text to a WAV file off the GUI thread (A10). Used when the
    requested page hasn't been narrated yet; otherwise NarrationPlayer
    exports its rendered buffer directly (captions included)."""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, engine, text, path, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.text = text
        self.path = path

    def run(self):
        try:
            if not hasattr(self.engine, "render_wav"):
                raise RuntimeError("WAV export needs a TTS voice")
            self.engine.render_wav(self.text, self.path)
            self.done.emit(self.path)
        except Exception as e:
            log.error("wav export failed: %s", e)
            self.failed.emit(str(e))

class NarrationPlayer(QThread):
    """Render-then-play narration engine (E9).

    The narrator renderer synthesizes sentence chunks to PCM off the GUI
    thread and appends them here (`append_chunk`); this thread walks the
    concatenated timeline, writing small blocks to the audio device.

    * Pause/resume is a frame pointer — sample-accurate; rendering keeps
      buffering ahead while paused, so resume is instant.
    * `begin(start_at=(page, chunk, frame))` starts a session optionally
      jumping to a persisted resume position once that chunk is appended.
    * Bookmarks are exact: every timeline entry carries its (page, chunk)
      tag and the offsets are prefix sums, so `position_changed` reports
      what the user has actually heard and `page_finished` fires only when
      a page's audio truly ran out.
    * Volume applies per block at write time — the slider is live.
    * Speed is baked in at render time (applies to chunks not yet
      synthesized, same as before).

    States (state_changed): rendering | playing | paused | underrun |
    finished | stopped. `underrun` = playback caught up with the renderer
    (e.g. a vision call is describing an image) and is waiting for more.
    """

    state_changed = pyqtSignal(str)
    position_changed = pyqtSignal(int, int)   # (page, chunk) heard up to
    page_finished = pyqtSignal(int)           # a page's audio played to the end
    failed = pyqtSignal(str)

    _BLOCK = 4096   # frames per device write (~0.19 s at 22 kHz)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._lock = threading.Lock()
        self._timeline = []       # {samples, sr, page, chunk}
        self._offsets = []        # cumulative frame offset at each entry start
        self._total = 0           # frames appended so far
        self._render_done = True
        self._frame_pos = 0
        self._playing = False
        self._paused = False
        self._stop_flag = True
        self._stream_reset = False  # player thread swaps the stream between writes
        self._volume = 1.0
        self._start_at = None     # (page, chunk, frame) resume target
        self._state = "stopped"
        self._last_pos_key = None
        self._stream = None
        self._stream_sr = 0

    # ── main-thread API ────────────────────────────────────────────────────
    # NB: the GUI thread NEVER touches the audio stream. Stopping/starting/
    # closing a PortAudio stream from another thread while a write is in
    # flight tears down the ALSA PCM underneath it ("File descriptor in bad
    # state", at best; SIGSEGV at worst) — so begin/pause/stop only set
    # flags, and the player thread does all stream work between writes.
    def begin(self, start_at=None):
        """Start a new narration session: reset the timeline; playback will
        start as soon as the renderer appends the first chunk."""
        with self._lock:
            self._timeline = []
            self._offsets = []
            self._total = 0
            self._frame_pos = 0
            self._render_done = False
            self._playing = True
            self._paused = False
            self._stop_flag = False
            self._start_at = start_at
            self._last_pos_key = None
            self._stream_reset = True   # thread closes the old stream safely
        self._set_state("rendering")
        if not self.isRunning():
            self.start()

    def append_chunk(self, samples, page, chunk, sr):
        if samples is None or len(samples) == 0:
            return
        with self._lock:
            if self._start_at is not None:
                tgt = self._start_at
                if (page, chunk) == tgt[:2]:
                    # Jump to the persisted position — may point into later
                    # sentences of the same chunk; playback simply waits for
                    # those frames to exist.
                    self._frame_pos = self._total + tgt[2]
                    self._start_at = None
                elif page is not None and (page, chunk) > tgt[:2]:
                    # Chunks arrive in order — we're past the target without
                    # matching it (index drift between sessions): drop it.
                    self._start_at = None
            self._timeline.append({"samples": samples, "sr": sr,
                                   "page": page, "chunk": chunk})
            self._offsets.append(self._total)
            self._total += len(samples)
        if not self.isRunning():
            self.start()

    def render_finished(self):
        with self._lock:
            self._render_done = True

    def pause(self):
        with self._lock:
            if self._playing:
                self._paused = True
        self._set_state("paused")

    def resume(self):
        with self._lock:
            self._paused = False
        self._set_state("playing")

    def stop(self):
        """Stop playback, clear the timeline, and exit the thread."""
        with self._lock:
            self._stop_flag = True
            self._playing = False
            self._paused = False
            self._timeline = []
            self._offsets = []
            self._total = 0
            self._frame_pos = 0
            self._render_done = True
            self._stream_reset = True
        self._set_state("stopped")
        self.wait(3000)

    def set_volume(self, v):
        self._volume = max(0.0, min(v, 1.0))

    def state(self):
        return self._state

    def is_active(self):
        return self._state in ("rendering", "playing", "paused", "underrun")

    def is_paused(self):
        return self._paused and self._playing

    def current_position(self):
        """(page, chunk, frame_within_chunk) the user has heard up to —
        the point that should be persisted for cross-session resume."""
        with self._lock:
            return self._position_locked(self._frame_pos)

    def active_page(self):
        with self._lock:
            for e in reversed(self._timeline):
                if e["page"] is not None:
                    return e["page"]
        return None

    def save_wav(self, path):
        """Write the rendered timeline (captions included) to a WAV file.
        Returns True if there was audio to save."""
        with self._lock:
            if not self._timeline:
                return False
            sr = self._timeline[0]["sr"]
            import numpy as np
            data = np.concatenate([e["samples"] for e in self._timeline])
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(data.tobytes())
        return True

    # ── internals ──────────────────────────────────────────────────────────
    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _entry_at_locked(self, frame):
        """Timeline index containing playback frame `frame`."""
        lo, hi, idx = 0, len(self._offsets) - 1, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._offsets[mid] <= frame:
                idx = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return idx

    def _slice_locked(self, pos, count):
        import numpy as np
        parts, remaining = [], count
        i = self._entry_at_locked(pos)
        off = pos - self._offsets[i]
        while remaining > 0 and i < len(self._timeline):
            s = self._timeline[i]["samples"][off:off + remaining]
            parts.append(s)
            remaining -= len(s)
            i += 1
            off = 0
        return parts[0] if len(parts) == 1 else np.concatenate(parts)

    def _position_locked(self, frame_pos):
        """Map a frame position to (page, chunk, frame-within-chunk)."""
        if not self._timeline or frame_pos <= 0:
            return None, -1, 0
        i = self._entry_at_locked(min(frame_pos, self._total) - 1)
        e = self._timeline[i]
        if e["page"] is None:
            return None, -1, 0
        # Frame offset relative to the chunk's FIRST sentence, so a saved
        # position maps exactly onto the re-rendered chunk on resume.
        chunk_start = self._offsets[i]
        j = i
        while j > 0 and self._same_chunk(self._timeline[j - 1], e):
            j -= 1
            chunk_start = self._offsets[j]
        return e["page"], e["chunk"], frame_pos - chunk_start

    @staticmethod
    def _same_chunk(a, b):
        return a["page"] is not None and a["page"] == b["page"] and a["chunk"] == b["chunk"]

    def _last_page_locked(self):
        for e in reversed(self._timeline):
            if e["page"] is not None:
                return e["page"]
        return None

    def _close_stream_locked(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._stream_sr = 0

    def _ensure_stream(self, sd, sr):
        """Create (or reconfigure) the OutputStream — player thread only."""
        if self._stream is not None and self._stream_sr == sr:
            if not self._stream.active:
                self._stream.start()   # resumed after a pause
            return
        self._close_stream_locked()
        self._stream = sd.OutputStream(
            samplerate=sr, channels=1, dtype="int16")
        self._stream.start()
        self._stream_sr = sr

    # ── playback thread ────────────────────────────────────────────────────
    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            while True:
                data = None
                entry = None
                done_now = False
                last_page = None
                playing = paused = False
                with self._lock:
                    if self._stop_flag:
                        break
                    if self._stream_reset:
                        # Session swap requested (begin/stop): safe point —
                        # this thread is between writes.
                        self._close_stream_locked()
                        self._stream_reset = False
                    playing = self._playing
                    paused = self._paused
                    if playing and not paused:
                        avail = self._total - self._frame_pos
                        if avail <= 0:
                            if self._render_done:
                                self._playing = False
                                done_now = True
                                last_page = self._last_page_locked()
                        else:
                            count = min(avail, self._BLOCK)
                            data = self._slice_locked(self._frame_pos, count)
                            entry = self._timeline[self._entry_at_locked(
                                self._frame_pos + count - 1)]
                            self._frame_pos += count
                if data is not None:
                    if self._volume != 1.0:
                        scaled = data.astype(np.float32) * self._volume
                        data = np.clip(scaled, -32767, 32767).astype(np.int16)
                    try:
                        self._ensure_stream(sd, entry["sr"])
                        self._set_state("playing")
                        self._stream.write(data)
                    except Exception as e:
                        # A dead stream must never kill the thread: rewind the
                        # block so it replays on a fresh stream.
                        log.warning("audio write failed, rebuilding stream: %s", e)
                        with self._lock:
                            self._frame_pos = max(0, self._frame_pos - len(data))
                            self._close_stream_locked()
                        time.sleep(0.05)
                        continue
                    with self._lock:
                        page, chunk, _ = self._position_locked(self._frame_pos)
                    if page is not None and (page, chunk) != self._last_pos_key:
                        self._last_pos_key = (page, chunk)
                        self.position_changed.emit(page, chunk)
                elif done_now:
                    with self._lock:
                        self._close_stream_locked()
                    if last_page is not None:
                        self.page_finished.emit(last_page)
                    self._set_state("finished")
                    break
                elif not playing:
                    time.sleep(0.05)
                elif paused:
                    with self._lock:
                        if self._stream is not None and self._stream.active:
                            try:
                                self._stream.stop()   # between writes: safe
                            except Exception:
                                pass
                    self._set_state("paused")
                    time.sleep(0.05)
                else:
                    # Playback caught up with the renderer (vision call…)
                    self._set_state("underrun")
                    time.sleep(0.1)
        except Exception as e:
            log.exception("narration player failed")
            self.failed.emit(str(e))
        finally:
            with self._lock:
                self._close_stream_locked()
                self._stop_flag = True
                self._playing = False
