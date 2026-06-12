# AGENTS.md

## What this is
Single-binary Rust app: a native GUI PDF reader. Crate name `ai-pdf` (Cargo.toml:1). No workspace, no library crate, no `[[bin]]` section — Cargo auto-discovers `src/main.rs`.

## Build & run
- Build: `cargo build --release`
- Run: `cargo run --release` (opens welcome screen) or `cargo run --release -- <file.pdf>` (auto-opens a file)
- The PDFium native library is downloaded automatically on first run by `pdfium-auto` (see `engine::document::ensure_pdfium`, src/engine/document.rs:16). Requires network on first run; progress is logged via `tracing`.
- No tests, no `rustfmt.toml`, no `clippy.toml`, no CI, no `.github/`. Do not invent a test framework — match the existing zero-config style.

## Architecture
- `src/main.rs` (908 lines) — entire Iced 0.13 application. `AiPdfApp` with `update`/`view`/`subscription`/`handle_key`, plus a `Message` enum that owns every event (keyboard, scroll, search, zoom, bookmarks, render results, periodic `Tick`).
- `src/engine/mod.rs` — module root, defines `EngineError`.
- `src/engine/document.rs` — `PdfDoc` wraps PDFium; `ensure_pdfium()` lazily initializes a `OnceLock<Pdfium>` global, downloading/binding the native lib on first call.
- `src/engine/renderer.rs` — `PageRenderer` with an LRU bitmap cache (max 50 entries, `MAX_CACHED_BITMAPS` at src/engine/renderer.rs:9). Call `invalidate_zoom()` when zoom changes; cache is keyed by page index, invalidated when width no longer matches.
- `lopdf` is used alongside PDFium **only** for things PDFium doesn't expose cleanly: bookmarks/TOC and PDF version metadata (src/main.rs:850, src/main.rs:876). Don't replace PDFium with lopdf for rendering/text — keep the split.

## Conventions specific to this repo
- Logging: `tracing_subscriber` initialized with env-filter, directive `ai_pdf=info` (src/main.rs:23-29). Respect it for new logs; don't pull in `println!` or `eprintln!`.
- Blocking PDFium calls are wrapped in `tokio::task::spawn_blocking` (e.g. `init_pdfium`, `load_pdf`, `open_file_dialog` in src/main.rs). Keep new sync PDFium work off the Iced runtime thread the same way.
- Iced features in use: `wgpu`, `image`, `tokio`. Don't enable other Iced features without a reason — match Cargo.toml.
- Window is 1400×900, dark theme forced (src/main.rs:33-34).
- Keyboard shortcuts are centralized in `handle_key` (src/main.rs:343). When adding a new shortcut, add it there and also to the README table.
- Default zoom state: `fit_to_width = true`, `zoom_index = 5` (ZOOM_LEVELS index for 1.0). `ZOOM_LEVELS` is at src/main.rs:20.
- Page rendering uses `PdfRenderConfig::set_target_width` + `set_maximum_height(30_000)` (src/engine/document.rs:139-141). Changing the render config affects cache invalidation behavior in `PageRenderer`.
- The `Message` enum is exhaustive; new actions need a new variant + an `update` arm + (if user-facing) a `view` element.

## Things an agent would likely miss
- No test infrastructure exists — `cargo test` will report 0 tests. Don't add a test harness unsolicited.
- No CI, no formatter/lint config. Match the existing hand-written style (4-space indent, no trailing commas in single-line blocks visible throughout).
- `engine::document::PDFIUM` is a process-global `OnceLock`. Tests or parallel operations must assume a single initialized engine.
- The cache invalidation contract: zoom changes must call `invalidate_zoom()`; otherwise stale bitmaps at the wrong width are returned (checked at src/engine/renderer.rs:64-67).
- The `with_document` helper (src/engine/document.rs:120) re-parses the PDF from the in-memory `file_data` for each call — this is intentional, not a bug, because `pdfium-render` doesn't expose a cheap clone of `PdfDocument`. Avoid stacking many sequential `with_document` calls in a hot loop without `spawn_blocking`.

## Files worth knowing
- Entry point: `src/main.rs:22` (`fn main`)
- Engine init: `src/engine/document.rs:16` (`ensure_pdfium`)
- Cache: `src/engine/renderer.rs:13`
- All keyboard shortcuts: `src/main.rs:343`
- All `Message` variants and arms: `src/main.rs:69-93` and `src/main.rs:153-340`
