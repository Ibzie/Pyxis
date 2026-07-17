import re
import gc
import base64
import logging
import platform

log = logging.getLogger("ai_layer")

# ── Model tiers ────────────────────────────────────────────────────────────
# Two families live in one flat list (preserves `tier_idx` indexing used by
# the model menu). `pick_model` only considers the Gemma 4 auto-pick family.
# Gemma 4 (https://huggingface.co/unsloth/gemma-4-*) is multimodal — text +
# image + audio (E2B/E4B) — so the AI can describe PDF figures for blind
# users. Qwen2.5 is retained as a text-only fallback for users who want
# maximum pure-text quality and don't need image understanding.
TIERS = [
    # ── Gemma 4 family (auto-pick, multimodal) ──────────────────────────────
    {"min_ram": 16, "name": "Gemma 4 12B-it", "footprint": 7.5, "family": "Gemma 4",
     "multimodal": True,
     "repos": ["unsloth/gemma-4-12b-it-GGUF"],
     "quants": ["Q4_K_M", "IQ4_XS", "Q5_K_M", "Q3_K_M"]},
    {"min_ram": 14, "name": "Gemma 4 12B-it", "footprint": 6.8, "family": "Gemma 4",
     "multimodal": True,
     "repos": ["unsloth/gemma-4-12b-it-GGUF"],
     "quants": ["IQ4_XS", "Q4_K_M", "Q3_K_M"]},
    {"min_ram": 12, "name": "Gemma 4 E4B-it", "footprint": 5.5, "family": "Gemma 4",
     "multimodal": True,
     "repos": ["unsloth/gemma-4-E4B-it-GGUF"],
     "quants": ["Q4_K_M", "IQ4_XS", "Q5_K_M", "Q3_K_M"]},
    {"min_ram": 10, "name": "Gemma 4 E4B-it", "footprint": 5.0, "family": "Gemma 4",
     "multimodal": True,
     "repos": ["unsloth/gemma-4-E4B-it-GGUF"],
     "quants": ["IQ4_XS", "Q4_K_M", "Q3_K_M"]},
    {"min_ram": 8, "name": "Gemma 4 E2B-it", "footprint": 3.5, "family": "Gemma 4",
     "multimodal": True,
     "repos": ["unsloth/gemma-4-E2B-it-GGUF"],
     "quants": ["Q4_K_M", "IQ4_XS", "Q3_K_M", "Q4_0"]},
    # ── Qwen2.5 family (text-only, manual selection) ───────────────────────
    {"min_ram": 16, "name": "Qwen2.5-14B-Instruct", "footprint": 10.5, "family": "Qwen2.5",
     "multimodal": False,
     "repos": ["Qwen/Qwen2.5-14B-Instruct-GGUF"],
     "quants": ["Q5_K_M", "Q4_K_M", "Q3_K_M"]},
    {"min_ram": 14, "name": "Qwen2.5-14B-Instruct", "footprint": 9.5, "family": "Qwen2.5",
     "multimodal": False,
     "repos": ["Qwen/Qwen2.5-14B-Instruct-GGUF"],
     "quants": ["Q4_K_M", "Q5_K_M", "Q3_K_M"]},
    {"min_ram": 10, "name": "Qwen2.5-7B-Instruct", "footprint": 4.7, "family": "Qwen2.5",
     "multimodal": False,
     "repos": ["Qwen/Qwen2.5-7B-Instruct-GGUF"],
     "quants": ["Q4_K_M", "Q5_K_M", "Q3_K_M"]},
    {"min_ram": 8, "name": "Qwen2.5-3B-Instruct", "footprint": 2.0, "family": "Qwen2.5",
     "multimodal": False,
     "repos": ["Qwen/Qwen2.5-3B-Instruct-GGUF"],
     "quants": ["Q4_K_M", "Q5_K_M", "Q3_K_M", "Q4_0"]},
]

HEADROOM_GB = 2.5
N_CTX = 8192
MAX_TOKENS = 700
MAX_IMG_TOKENS = 400
MMPROJ_FILENAME = "mmproj-F16.gguf"

# KV-cache quant: `type_k` takes the ggml type *integer* enum (not a string).
# We only quantize the K cache (q8_0, near-lossless); quantizing V to q4_0 is
# unsupported on some llama.cpp builds (e.g. Qwen attention) and makes context
# creation fail, so V stays the default f16.
try:
    from llama_cpp import GGML_TYPE_F16 as _F16, GGML_TYPE_Q8_0 as _Q8_0, GGML_TYPE_Q4_0 as _Q4_0
except Exception:
    _F16, _Q8_0, _Q4_0 = 1, 8, 2
KV_K_LOSSLESS = _Q8_0
KV_K_TIGHT = _Q4_0


def detect_capacity():
    """Return (budget_ram_gb, accelerator). Uses 85% of TOTAL system RAM so the
    fit-level is stable and reflects the machine, not transient available RAM."""
    try:
        import psutil
        ram = psutil.virtual_memory().total / (1024 ** 3) * 0.85
    except Exception:
        ram = 8.0
    accel = "cpu"
    if platform.system() == "Darwin":
        accel = "metal"
    else:
        try:
            import pynvml
            pynvml.nvmlInit()
            accel = "cuda"
            pynvml.nvmlShutdown()
        except Exception:
            accel = "cpu"
    return ram, accel


def ensure_gpu_native(on_status=None):
    """If the bundled llama-cpp-python is CPU-only but a CUDA GPU is detected,
    download a CUDA-built ``libllama`` shared library into the app's data
    directory and prepend that directory to ``LD_LIBRARY_PATH`` / ``PATH``.

    Returns True if the app should restart to pick up the new library.
    The caller (``main.py``) is responsible for actually restarting."""
    import sys
    if sys.platform == "darwin":
        return False   # Metal is built into the default wheel; no swap needed
    try:
        import pynvml
        pynvml.nvmlInit()
        pynvml.nvmlShutdown()
    except Exception:
        return False   # no NVIDIA GPU → nothing to do
    # Check if the bundled llama already supports CUDA.
    try:
        from llama_cpp import Llama
        # Heuristic: if llama.cpp was built with CUDA, the ggml-cuda lib is
        # loaded at import time. We can check by looking at loaded shared libs.
        import llama_cpp
        lib_dir = Path(llama_cpp.__file__).parent
        has_cuda = any(
            ("cuda" in f.name.lower() or "cublas" in f.name.lower())
            for f in lib_dir.rglob("*")
        )
        if has_cuda:
            return False   # already GPU-enabled
    except Exception:
        pass
    # Download the CUDA-built libllama for this platform.
    from storage import app_data_dir
    native_dir = app_data_dir() / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        lib_name = "llama.dll"
        asset_name = "llama-cuda-win-x64.dll"
    else:
        lib_name = "libllama.so"
        asset_name = "libllama-cuda12-linux-x64.so"
    lib_path = native_dir / lib_name
    if lib_path.exists():
        _inject_native_dir(native_dir)
        return False   # already downloaded — just inject and continue
    if on_status:
        on_status("Downloading CUDA build for faster AI (~15 MB)…")
    try:
        from huggingface_hub import hf_hub_download
        # Host the CUDA libs in a dedicated HF repo (or GitHub releases).
        # Using HF keeps the download path consistent with model downloads.
        downloaded = hf_hub_download(
            repo_id="pyxis/native-libs",
            filename=asset_name,
            cache_dir=str(native_dir.parent / "native-cache"),
        )
        import shutil
        shutil.copy2(downloaded, lib_path)
    except Exception as e:
        log.warning("CUDA lib download failed: %s", e)
        return False
    _inject_native_dir(native_dir)
    return True   # restart recommended — native lib loads at import time


def _inject_native_dir(native_dir):
    """Prepend the native-lib dir to the library search path."""
    import os
    path_var = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    current = os.environ.get(path_var, "")
    os.environ[path_var] = str(native_dir) + (os.pathsep + current if current else "")


def pick_model(ram_gb):
    """Auto-pick the largest Gemma 4 (multimodal) model that fits with EASY
    headroom (1.5x + 2.5 GB) so the first-run download is reasonably sized.
    Qwen2.5 (text-only) and Tight/Overflow tiers are still available via the
    manual dropdown in the model menu."""
    for tier in TIERS:
        if tier.get("family") != "Gemma 4":
            continue
        if ram_gb >= tier["min_ram"] and ram_gb >= tier["footprint"] * 1.5 + HEADROOM_GB:
            return tier
    # Fall back to smallest Gemma 4 if nothing fits — never auto-pick Qwen2.5.
    gemma4 = [t for t in TIERS if t.get("family") == "Gemma 4"]
    return gemma4[-1] if gemma4 else TIERS[-1]


def fit_level(footprint, ram_gb):
    """Return (label, color_hex) for how well a model fits in RAM."""
    if ram_gb >= footprint * 1.5 + HEADROOM_GB:
        return "Easy", "#4caf50"
    if ram_gb >= footprint + HEADROOM_GB:
        return "Tight", "#FFC107"
    return "Overflow", "#f44336"


def resolve_quant(repo_id, quants, on_status=None):
    """Return the ordered list of GGUF filenames in `repo_id` for the first
    preferred quant that exists.

    Multi-shard quants (e.g. Qwen 7B+ ``q4_k_m`` split into two files) return
    every shard in order so `load_model` can pass the first to ``filename=``
    and the rest to ``additional_files=``. Sidecars (``mmproj`` / ``mtp``)
    are excluded — they are vision/draft modules, not the LLM weights.
    """
    from huggingface_hub import HfApi
    if on_status:
        on_status(f"Listing quants for {repo_id}…")
    try:
        files = HfApi().list_repo_files(repo_id)
    except Exception as e:
        raise RuntimeError(f"Could not list {repo_id}: {e}")
    ggufs = []
    for f in files:
        base = f.lower()
        if not base.endswith(".gguf"):
            continue
        if "mmproj" in base or base.startswith("mtp") or "/mtp" in base:
            continue
        ggufs.append(f)
    if not ggufs:
        raise RuntimeError(f"No .gguf model files in {repo_id}")
    for pref in quants:
        matched = []
        for f in ggufs:
            base = f.split("/")[-1]
            if re.search(r"(?i)(^|[^\w])(" + re.escape(pref) + r")([^\w]|$)", base):
                matched.append(f)
        if matched:
            return _sort_shards(matched)
    # Last resort: smallest non-sharded GGUF (likely the lowest-bit quant).
    singles = [f for f in ggufs if "of-" not in f]
    return [_sort_shards(singles or ggufs)[0]]


def _sort_shards(files):
    def key(f):
        m = re.search(r"-(\d{5})-of-\d{5}", f)
        return (int(m.group(1)) if m else 0, f)
    return sorted(files, key=key)


class _SignalTqdm:
    """A tqdm stand-in whose updates are mirrored to a (done, total, label)
    callback so a QProgressBar can mirror real byte progress.

    `huggingface_hub.hf_hub_download(tqdm_class=...)` instantiates this class
    with the same kwargs as `tqdm.tqdm`; we just forward `update`/`close` to the
    registered callback while doing no terminal I/O.
    """
    _callback = None

    def __init__(self, iterable=None,desc=None, total=None, unit=None, unit_scale=False, **_):
        self._n = 0
        self._total = int(total) if total else 0
        self._desc = desc or ""
        self._fired()
        # If an iterable was passed, iterate it (rare for hf downloads).
        if iterable is not None:
            for _ in iterable:
                self.update(1)

    def _fired(self):
        if _SignalTqdm._callback:
            _SignalTqdm._callback(self._n, self._total, self._desc)

    def update(self, n=1):
        self._n += n
        self._fired()

    def set_description(self, desc=None):
        if desc:
            self._desc = desc
        self._fired()

    def set_postfix(self, *a, **k):
        pass

    def refresh(self):
        self._fired()

    def close(self):
        self._fired()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class AILayer:
    def __init__(self):
        self.llm = None
        self.tier = None
        self.repo_id = None
        self.filename = None
        self.accel = "cpu"
        self._cancel = False
        self._handler = None      # Gemma4ChatHandler (vision), or None for text-only tiers

    def is_multimodal(self):
        return bool(self.tier and self.tier.get("multimodal") and self._handler)

    # ── loading ────────────────────────────────────────────────────────────
    def load_model(self, on_status=None, on_progress=None, repo_id=None, filename=None, tier_idx=None):
        ram, self.accel = detect_capacity()
        log.info("capacity: %.1f GB, accel=%s", ram, self.accel)
        if on_status:
            on_status(f"Detected {ram:.1f} GB RAM, accelerator: {self.accel}")
        self.tier = TIERS[tier_idx] if tier_idx is not None else pick_model(ram)
        log.info("tier: %s (footprint %.1f GB, multimodal=%s)",
                 self.tier["name"], self.tier["footprint"], self.tier.get("multimodal"))
        self.repo_id = repo_id or self._first_available_repo(self.tier["repos"], on_status)
        files = [filename] if filename else resolve_quant(
            self.repo_id, self.tier["quants"], on_status)
        self.filename = files[0]
        self._download(files, on_status, on_progress)
        # Multimodal tiers (Gemma 4) need the mmproj sidecar so the loaded
        # model can process images. We download and attach a Gemma4ChatHandler
        # up-front; text-only inference is unaffected.
        handler = None
        if self.tier.get("multimodal"):
            self._download([MMPROJ_FILENAME], on_status, on_progress)
            if on_status:
                on_status("Preparing vision projector…")
            try:
                from llama_cpp.llama_chat_format import Gemma4ChatHandler
                handler = Gemma4ChatHandler.from_pretrained(
                    repo_id=self.repo_id, filename=MMPROJ_FILENAME,
                    use_gpu=self.accel != "cpu", verbose=False,
                )
                log.info("vision handler ready: %s", MMPROJ_FILENAME)
            except Exception as e:
                log.warning("vision handler unavailable: %s", e)
                if on_status:
                    on_status(f"Vision unavailable (continuing text-only): {e}")
        self._handler = handler
        kvk = KV_K_LOSSLESS if ram >= 12 else KV_K_TIGHT
        if on_status:
            on_status(f"Loading {self.tier['name']} ({self.quant_label()})…")
        # Try GPU first, then progressively safer CPU fallbacks so a tight-RAM
        # machine never crashes on context creation. Each failure is cleaned
        # up so the failed mmap weights don't pollute RAM for the next attempt.
        attempts = []
        if self.accel != "cpu":
            attempts.append((N_CTX, -1, kvk))
        attempts += [
            (N_CTX, 0, kvk),
            (N_CTX, 0, KV_K_TIGHT),
            (4096, 0, KV_K_TIGHT),
            (2048, 0, KV_K_TIGHT),
        ]
        from llama_cpp import Llama
        for n_ctx, n_gpu, _kvk in attempts:
            kwargs = dict(
                repo_id=self.repo_id, filename=self.filename,
                n_ctx=n_ctx, n_gpu_layers=n_gpu, type_k=_kvk, verbose=False,
            )
            if len(files) > 1:
                kwargs["additional_files"] = files[1:]
            if handler is not None:
                kwargs["chat_handler"] = handler
            try:
                log.info("load attempt n_ctx=%d n_gpu=%d kv=%s", n_ctx, n_gpu, _kvk)
                self.llm = Llama.from_pretrained(**kwargs)
                self._loaded_n_ctx = n_ctx
                break
            except Exception as e:
                log.warning("context creation failed (n_ctx=%d, n_gpu=%d): %s", n_ctx, n_gpu, e)
                self.unload()
        if self.llm is None:
            raise RuntimeError("Could not allocate llama context — see ai_layer log")
        if on_status:
            on_status(f"Loaded {self.tier['name']} ({self.quant_label()})")
        log.info("loaded: %s, n_ctx=%d", self.tier['name'], self._loaded_n_ctx)

    def unload(self):
        """Release the loaded model and vision handler, reclaim resident RAM."""
        if self.llm is not None:
            try:
                del self.llm
            except Exception:
                pass
        self.llm = None
        if self._handler is not None:
            try:
                del self._handler
            except Exception:
                pass
        self._handler = None
        gc.collect()

    def _download(self, files, on_status=None, on_progress=None):
        from huggingface_hub import hf_hub_download
        from storage import app_data_dir
        cache_dir = app_data_dir() / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _SignalTqdm._callback = on_progress
        try:
            for i, fn in enumerate(files, 1):
                if on_status:
                    on_status(f"Downloading {fn} ({i}/{len(files)})…")
                hf_hub_download(
                    repo_id=self.repo_id, filename=fn,
                    cache_dir=str(cache_dir), tqdm_class=_SignalTqdm,
                )
        finally:
            _SignalTqdm._callback = None

    def _first_available_repo(self, repos, on_status):
        from huggingface_hub import HfApi
        api = HfApi()
        for r in repos:
            try:
                api.repo_info(r)
                return r
            except Exception:
                if on_status:
                    on_status(f"Repo {r} unavailable, trying next…")
        raise RuntimeError(f"None of {repos} were reachable")

    def is_loaded(self):
        return self.llm is not None

    def model_label(self):
        if not self.tier:
            return "AI: idle"
        return f"AI: {self.tier['name']} ({self.quant_label()})"

    def quant_label(self):
        if not self.filename:
            return ""
        m = re.search(r"(Q[0-9_]+[A-Z_]*|IQ[0-9_]+[A-Z_]*)", self.filename, re.I)
        return m.group(1).upper() if m else ""

    def request_cancel(self):
        self._cancel = True

    def reset_cancel(self):
        self._cancel = False

    @property
    def cancelled(self):
        return self._cancel

    # ── RAG query expansion ──────────────────────────────────────────────────
    def expand_query(self, question, doc_title=""):
        if not self.llm:
            return question
        prompt = (f"Expand this query into 3-8 pipe-separated search terms. "
                  f"Include the original words plus 2-3 synonyms. No prose.\n\n"
                  f"QUERY: {question}\nOUTPUT:")
        try:
            resp = self.llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80, stream=False, temperature=0.3,
            )
            return resp["choices"][0]["message"]["content"].strip()
        except Exception:
            return question

    # ── command dispatch ───────────────────────────────────────────────────
    # Each command returns (messages, heading) so the worker knows what to
    # prepend before streaming tokens into the notes file.
    def build_request(self, command, *, notes="", page_text="", page_idx=None, question="", context=""):
        sys = (
            "You are an AI note assistant embedded in a PDF reader. "
            "Write in clean Markdown only. Be concise and faithful to the source. "
            "Quote exact numbers, figures, and names verbatim from the source — "
            "never round, approximate, or paraphrase them. "
            "When you reference content from the user's notes or a page, keep the "
            "`Page N` markers that appear in the source."
        )
        if command == "summarize_notes":
            user = f"Summarize my notes into a Markdown bullet list.\n\nNOTES:\n{notes}"
            heading = "## AI — Summary"
        elif command == "summarize_page":
            user = (f"Summarize page {page_idx + 1} of the PDF into a Markdown "
                    f"bullet list.\n\nPAGE {page_idx + 1} TEXT:\n{page_text}")
            heading = f"## AI — Page {page_idx + 1} Summary"
        elif command == "answer":
            user = (f"Answer the question using the notes below. "
                    f"If the notes don't cover it, say so.\n\n"
                    f"QUESTION: {question}\n\nNOTES:\n{notes}")
            heading = "## AI — Answer"
        elif command == "answer_rag":
            user = (f"Answer using the context below. "
                    f"Quote exact numbers, figures, dates, and names from the context "
                    f"— do not round or paraphrase them. "
                    f"Cite page numbers as [Page N]. "
                    f"If the context doesn't contain the answer, say so.\n\n"
                    f"--- CONTEXT ---\n{context}\n--- END CONTEXT ---\n\n"
                    f"QUESTION: {question}")
            heading = "## AI — Answer"
        elif command == "extract_todos":
            user = f"Extract action items as a Markdown checklist.\n\nNOTES:\n{notes}"
            heading = "## AI — To-Dos"
        elif command == "suggest_tags":
            user = (f"Suggest 3-6 short tags for these notes as a single Markdown "
                    f"line of `#tag` tokens.\n\nNOTES:\n{notes}")
            heading = "## AI — Suggested Tags"
        elif command == "draft":
            user = (f"Draft a short follow-up note that ties together the themes in "
                    f"these notes.\n\nNOTES:\n{notes}")
            heading = "## AI — Draft"
        else:
            raise ValueError(f"Unknown command {command}")
        return [{"role": "system", "content": sys}, {"role": "user", "content": user}], heading

    # ── inference ──────────────────────────────────────────────────────────
    def generate(self, messages, on_token=None, enable_thinking=False):
        if not self.llm:
            raise RuntimeError("AI model not loaded")
        self.reset_cancel()
        # Gemma 4 thinking is toggled by a `<|think|>` token at the start of
        # the system prompt (per the model card). We inject it when the caller
        # asks for thinking, omit it otherwise. Non-Gemma models ignore the
        # token harmlessly.
        msgs = self._with_thinking(messages, enable_thinking)
        stream = self.llm.create_chat_completion(
            messages=msgs, stream=True, max_tokens=MAX_TOKENS
        )
        for chunk in stream:
            if self._cancel:
                break
            delta = chunk["choices"][0].get("delta", {})
            token = delta.get("content")
            if token and on_token:
                on_token(token)

    @staticmethod
    def _with_thinking(messages, enable_thinking):
        if not enable_thinking or not messages:
            return messages
        out = list(messages)
        if out[0].get("role") == "system":
            out[0] = dict(out[0])
            out[0]["content"] = "<|think|>\n" + out[0].get("content", "")
        return out

    # ── vision (image description for accessibility) ───────────────────────
    def describe_image(self, image_bytes, prompt=None, enable_thinking=False):
        """Describe a PNG/JPEG for a blind reader. Returns the caption text.

        Raises RuntimeError if the loaded model is text-only (e.g. user
        manually picked Qwen2.5 from the model menu)."""
        if not self.llm:
            raise RuntimeError("AI model not loaded")
        if not self.is_multimodal():
            raise RuntimeError(
                "Current model is text-only. Switch to a Gemma 4 tier in the "
                "AI menu to describe images.")
        if prompt is None:
            prompt = (
                "Describe this image for a blind reader. State the type "
                "(chart, photo, diagram, screenshot, table, or other), the "
                "key visible content, any text in the image, and the overall "
                "purpose. Keep it to 2-4 sentences."
            )
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ],
        }]
        if enable_thinking:
            messages = [{"role": "system", "content": "<|think|>\nYou are a vision assistant."}] + messages
        log.info("describe_image: %d bytes, thinking=%s", len(image_bytes), enable_thinking)
        resp = self.llm.create_chat_completion(
            messages=messages, stream=False, max_tokens=MAX_IMG_TOKENS,
        )
        return resp["choices"][0]["message"]["content"].strip()