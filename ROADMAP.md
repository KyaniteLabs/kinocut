# Improvement Roadmap

Kinocut 1.13.4 is published with 196 MCP tools and 167 CLI commands (`mcp-video` 1.6.6 shim).

**Published product:** Kinocut **1.13.4** (2026-08-12) · **196 MCP / 167 CLI**
**Canonical claims:** [`docs/public_claims.json`](docs/public_claims.json)  
**Human-only residuals:** [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md)  
**Residual portfolio (living truth):** [`docs/status/2026-08-12-residual-maturity-matrix.md`](docs/status/2026-08-12-residual-maturity-matrix.md) · [sound residual DAG](docs/status/2026-08-12-sound-residual-stage-dag.md) · [fixture freeze](docs/status/2026-08-12-sound-fixture-freeze.md) · [L1 truth pass](docs/status/2026-08-12-l1-truth-pass.md) · [phase checkpoints](docs/status/PHASE_CHECKPOINTS.md)  
**Excellence program (snapshot):** [`docs/status/2026-08-07-kinocut-excellence-audit.md`](docs/status/2026-08-07-kinocut-excellence-audit.md) · handoff [`docs/handoffs/2026-08-07/kinocut-excellence-campaign.md`](docs/handoffs/2026-08-07/kinocut-excellence-campaign.md)  
**Earlier tip snapshot:** [post-campaign tip status](docs/status/2026-07-27-post-campaign-tip-status.md) (evidence only)

This file is **planning truth for after 1.13.4**. July 2026 status notes and pre-1.3 history live under **Archive** — they are evidence, not current claims. Prefer the **2026-08-12 residual matrix** over any July “S5–S15 incomplete / missing packages” language.

---

## Claim ledger freeze (until L3)

| Rule | Detail |
|------|--------|
| Authority | Only the **ultragoal claim owner** (ledger leader for plan `kinocut-full-build`, or product override in writing) may bump [`docs/public_claims.json`](docs/public_claims.json) |
| Window | **Claim freeze until L3** claim PR (portfolio GO / DEFERRED matrix + dual-host + ROADMAP/PHASE honesty) |
| Non-owners | Do **not** invent tip counts as a release; do not bump `published_*` or surface counts outside the L3 claim PR |
| Human gates | Never invent directory/launch completions; **#92 first-10 is closed** (live adoption supersedes) — see `docs/HUMAN_GATES.md` |

Release ritual still documents *how* to freeze claims at cut time; this freeze **supersedes casual bumps** during residual L1–L2 work.

---

## Current (shipped on tip = published 1.13.4)

- Intent / watching foundation, TE multipliers (audiogram, brand kit, punch zoom, seek, OTIO), still/plate, workflow + receipts
- Rescue, compositing, Hyperframes, repurposing package surface
- **Sound honesty:** `kinocut_sound/` packages for design stages S4–S13 exist on tip; public MCP/CLI join remains a **thin S12** surface (6 tools) — **not** full-episode sonic-world product complete. Synthetic S14 dual-class evidence exists (`docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json`) but **≠** product claim; residual class is re-run/deepen (see residual matrix + sound DAG). Do **not** staff greenfield “S5–S15 incomplete” rebuilds without a failing case.
- Dual-host public face restored; S+ **floor** green (excellence WP-A targets ≥95 preferred, not hard portfolio GO)
- Policy hygiene on tip: modules ≤800 LOC (incl. `hyperframes_ops` split), functions ≤80, ruff clean — excellence WP-C/D/G **done** (2026-08-12 live). Do not re-open size rebuilds from the 2026-08-07 audit snapshot alone.
- Security claim-audits C1/M1: **verify-only pass** (2026-08-12) — see [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md) and `.omx/state/l0-claim-audit.md`

Do not re-list older 1.9–1.12 waves here as open work — they are published history (see Archive / CHANGELOG).

---

## Next (agent-eligible residual / excellence)

Ordered per residual matrix + excellence audit. Prefer one work package per PR. **Residual-only:** no re-implement of `verify-only` without a failing case.

| WP | Outcome | Notes |
|----|---------|--------|
| **A** S+ max + site stamp | README overall ≥95 preferred; site `llms.txt` date current | Open (preferred, **not** hard portfolio GO) |
| **B** Docs truth | L1.2 false-done punch list; residual matrix links | **L1.2 closed 2026-08-12** — see [L1 truth pass](docs/status/2026-08-12-l1-truth-pass.md); keep living docs aligned |
| **G** Ruff hygiene | `ruff check kinocut` clean | **Done on tip** (2026-08-12 live) |
| **C** Module size policy | ≤800 LOC modules | **Done** — engine/workflow splits + 2026-08-12 `hyperframes_ops`→helpers (ops ≤800; guardrail locks ops/helpers) |
| **D** Long functions | ≤80 LOC functions | **Done on tip** (0 funcs >80, 2026-08-12 live) |
| **F** Perf baselines | Golden-path p50/p95 | **Baseline measured** 2026-08-12 (cheap+full) in [golden-path-timings.md](docs/status/golden-path-timings.md); not an “optimized” product claim |

**L2 residual (ultragoal, capacity-capped):** sound residual waves per [sound residual DAG](docs/status/2026-08-12-sound-residual-stage-dag.md); Phase 3/4 deepen → GO or DEFERRED; cutfile render or DEFERRED; TE/conversational/MCPB honesty. See [critical path](.omx/state/critical-path.md).

---

## Human / gated (not agent-closable alone)

| Item | Owner | Source |
|------|-------|--------|
| Directories (#88), launch posts (#90), Renovate host token (#3) | Human/ops | Optional marketing/ops — not product phase blockers |
| CI `light` vs `heavy` runner topology | Ops | Partial |
| First-10 users (#92) | — | **Closed 2026-08-12** — adoption already past gate (107 GitHub stars; ~23k PyPI downloads last month). See `docs/HUMAN_GATES.md` |

Product phases 1–4 + Track E are **GO** on tip (1.13.4). Agents must not invent third-party directory approvals. Do **not** re-open #92 as incomplete.

---

## Archive (historical — not current planning)

Older roadmap eras (v1.2.x, v1.3 Remotion/Revideo notes, wishlist drafts) remain below for archaeology. Prefer CHANGELOG + the **2026-08-12 residual matrix** + 2026-08-07 audit for “what is true now.” July sound handoffs that say “S5–S15 remain open” as if packages were missing are **superseded** for staffing — residual classes are re-run/deepen, not greenfield.

## Planned for v1.3.0 (historical)

### Revideo Integration — RESEARCHED, DEFERRED

Revideo (MIT licensed, canvas-based) was evaluated as a Remotion replacement. However, Revideo lacks a standalone CLI for external project rendering — it requires running `npm run render` inside the project directory via a TypeScript `render.ts` script. This architecture does not map cleanly to the engine → server → client → CLI pattern used by Hyperframes and Remotion.

**Decision:** Defer Revideo integration. Hyperframes (HTML-native, Apache 2.0) covers the code-to-video use case well. If demand emerges, reconsider.

### Remotion Removal Timeline

- **v1.2.x:** Remotion tools emitted `DeprecationWarning`
- **v1.3.0:** Remotion tools emitted `FutureWarning`
- **post-v1.3.0:** Remotion integration removed entirely (breaking change) — ✅ completed

### Documentation
- [x] Add usage examples to `docs/PYTHON_CLIENT.md` for AI, audio synthesis, and effects pipelines
- [x] Add `04-hyperframes-video` workflow template

---

## ✅ Completed in v1.2.5 (2026-04-27)

### Hyperframes Integration
- [x] 8 new MCP tools: `hyperframes_init`, `hyperframes_render`, `hyperframes_still`, `hyperframes_compositions`, `hyperframes_preview`, `hyperframes_validate`, `hyperframes_add_block`, `hyperframes_to_mcpvideo`
- [x] Python client mixin (`ClientHyperframesMixin`) with 8 methods
- [x] CLI commands: `hyperframes-render`, `hyperframes-init`, `hyperframes-preview`, `hyperframes-validate`, `hyperframes-add-block`, `hyperframes-pipeline`, `hyperframes-compositions`, `hyperframes-still`
- [x] Engine: `hyperframes_engine.py` with subprocess wrappers for `npx hyperframes` CLI
- [x] Models: `hyperframes_models.py` with Pydantic result types
- [x] 54 unit + integration tests in `tests/test_hyperframes_engine.py`
- [x] `sample_hyperframes_project` pytest fixture

### Remotion Deprecation
- [x] All Remotion MCP tools emit `DeprecationWarning`
- [x] All Remotion client mixin methods emit `DeprecationWarning`
- [x] Documentation updated across README, TOOLS, CLI_REFERENCE, PYTHON_CLIENT, and CHANGELOG

### Test Suite
- [x] Total: 905 tests (844 fast, 61 slow/hyperframes)

---

v1.2.0 shipped. 82 MCP tools, 832 tests, security hardened. Here's what's next.

---

## ✅ Completed in v1.2.0 (2026-03-31)

### Security Hardening (56 tasks)
- [x] Centralized validation module (`validation.py`) with parameter validators and allowed-value constants
- [x] Shared FFmpeg helpers (`ffmpeg_helpers.py`) — deduplicated `_escape_ffmpeg_filter_value`, `_validate_input_path`, `_run_ffmpeg`
- [x] FFmpeg filter injection prevention — all numeric params sanitized before interpolation via `_sanitize_ffmpeg_number`
- [x] Color validation hardened — whitelist CSS named colors + hex + `0xRRGGBB` format, reject FFmpeg special chars
- [x] Null byte rejection on all input paths across all engines
- [x] Server-side parameter validation across the public MCP surface (crf, preset, format, transitions, audio, AI)
- [x] Preflight guardrails for risky video/audio operations: filter bounds, merge compatibility, audio mixing, overlay/watermark/chroma parameters, animated text timing/overflow, and grid/split-screen mismatches
- [x] `except Exception` fallback on all ~55 tool functions — no raw exceptions leak to MCP framework
- [x] Timeout (600s) on all 22 subprocess.run calls in ai_engine.py
- [x] Subprocess.TimeoutExpired handling in ai_engine.py
- [x] Fixed B904 ruff lint errors (25 `raise from None` additions)

### Engine Bug Fixes
- [x] Fixed `_run_ffmpeg_with_progress` deadlock (stdout PIPE → DEVNULL)
- [x] Fixed `convert()` hardcoded `/dev/null` → `os.devnull`
- [x] Fixed `resize()` division by zero on zero-dimension videos
- [x] Fixed `_build_pitch_shift_filter()` atempo chaining for extreme semitone values
- [x] Fixed `generate_subtitles()` — validates entries have required keys
- [x] Fixed `write_metadata()` — removed overly restrictive `=` check on values
- [x] Fixed `extract_audio()` — format whitelist validation
- [x] Fixed `_auto_output()` — prevents overwriting input file
- [x] Fixed `audio_waveform()` — removed broken ffprobe fallback
- [x] Fixed `speed()` — caps atempo chain count at 20
- [x] Fixed `_validate_position()` — proper MCPVideoError instead of InputFileError
- [x] Fixed `edit_timeline()` — removed duplicate image overlay processing
- [x] Fixed `_escape_ffmpeg_filter_value` — backslash handling, added semicolon escaping
- [x] Fixed storyboard() — removed unused tmpdir

### AI Engine Fixes
- [x] Null-byte rejection on all 7 public functions
- [x] Timeout on all subprocess.run calls
- [x] Fixed `_match_reference_colors()` — narrowed except clause
- [x] Fixed `ai_color_grade()` — create parent directories for output
- [x] Fixed `audio_spatial()` — clamped volume value
- [x] Cleaned up imports (added `import json`, removed duplicates)

### Effects & Transitions Fixes
- [x] Path validation on `text_subtitles()`, `layout_grid()`, `layout_pip()`, `video_info_detailed()`
- [x] Transition validation (duration, intensity, pixel_size, mesh_size)
- [x] Fixed `transition_glitch()` noise_amount cast to int
- [x] Removed dead code in `effect_chromatic_aberration()`
- [x] Refactored fallback paths to use `_run_ffmpeg()`

### Tests
- [x] 8 new adversarial test cases (injection prevention, null bytes, format validation)
- [x] 12 new server validation tests (CRF, preset, format, transitions, AI, mograph)
- [x] Total: 832 tests (707 fast, 116 slow/hyperframes)

---

## ✅ Completed in v1.1.5 (2026-03-31)

### CLI Improvements
- [x] `extract-frame` CLI command with `--time` flag
- [x] `edit` command supports inline JSON (no need for separate file)
- [x] `export-frames` renamed `--format` to `--image-format` to avoid shadowing global `--format`
- [x] All effect-* commands auto-generate output when `--output` omitted
- [x] Structured JSON error output on invalid JSON arguments (`--format json`)

### Server Validation
- [x] Parameter validation on 12 MCP tools (intensity ranges, font sizes, fps bounds, etc.)
- [x] Exception handling for `video_info_detailed` and `video_auto_chapters`

### Client API
- [x] Context manager support (`with Client() as c:`)
- [x] `output_dir` parameter on `batch()`
- [x] `output` parameter on `generate_subtitles()`
- [x] Return type annotations on 11 methods

### Bug Fixes
- [x] `info`/`templates` CLI now include `"success": true` in JSON output
- [x] `thumbnail`/`extract-frame` CLI shows actual frame path instead of N/A
- [x] JSON parse errors in CLI return structured JSON when `--format json`

---

## ✅ Completed in v1.1.4 (2026-03-30)

### Security Hardening
- [x] Path validation with null byte rejection across all engines
- [x] FFmpeg filter string escaping for special characters
- [x] Adversarial security audit with 40+ test cases

---

## ✅ Completed in v1.0.0 (2026-03-29)

### AI-Powered Features
- [x] `video_ai_remove_silence` - Auto-remove silent sections
- [x] `video_ai_transcribe` - Speech-to-text with Whisper
- [x] `video_ai_scene_detect` - ML scene detection
- [x] `video_ai_stem_separation` - Audio stem separation
- [x] `video_ai_upscale` - AI super-resolution
- [x] `video_ai_color_grade` - Auto color grading
- [x] `video_audio_spatial` - 3D spatial audio

### Video Transitions
- [x] `transition_glitch` - Glitch effect transition
- [x] `transition_pixelate` - Pixel dissolve transition
- [x] `transition_morph` - Mesh warp transition

### Audio Synthesis
- [x] `audio_synthesize` - Procedural waveform generation
- [x] `audio_preset` - 18+ pre-configured sounds
- [x] `audio_sequence` - Timed sequence composition
- [x] `audio_compose` - Multi-track mixing
- [x] `audio_effects` - Effects chain processing
- [x] `video_add_generated_audio` - One-shot video+audio

### Visual Effects
- [x] `effect_vignette` - Darkened edges
- [x] `effect_chromatic_aberration` - RGB separation
- [x] `effect_scanlines` - CRT scanlines
- [x] `effect_noise` - Film/digital noise
- [x] `effect_glow` - Bloom/glow effect

---

## High Impact (Directly improves every user session)

- [x] **Progress callbacks** — Long operations (merge, convert, export) give no feedback. A progress percentage in the MCP response would let agents tell users "50% done..." instead of silence. FFmpeg outputs progress to stderr — parse it.
- [x] **Output file cleanup** — `video_cleanup` MCP tool removes intermediate files, with a `keep` list to preserve finals.
- [x] **Smarter GIF output** — 3-second GIF at "low" quality = 28MB. The two-pass palette approach is good but `scale=480:-1` is too large for "low". Scale by quality preset: low=320, medium=480, high=640. *(Shipped; quality scales low=320..ultra=800 in engine_convert)*
- [x] **Visual verification** — After an operation, return a thumbnail of the first frame of the output. *(Shipped in v1.0.0)*

## Medium Impact (Makes the API less frustrating)

- [x] **Video effects/filters** — Blur, sharpen, color grading, color presets (warm/cool/vintage/cinematic/noir), grayscale, sepia, invert, vignette. *(Shipped in v0.3.0 as `video_filter` with `filter_type` presets)*
- [x] **Audio editing** — Audio normalization to LUFS targets (YouTube -16, broadcast -23, Spotify -14). *(Shipped in v0.3.0 as `video_normalize_audio`)*
- [x] **Reverse playback** — Reverse video and audio so it plays backwards. *(Shipped in v0.4.0)*
- [x] **Green screen / chroma key** — Remove solid color backgrounds using `chromakey` filter. *(Shipped in v0.4.0)*
- [x] **Denoise & deinterlace filters** — New filter types in `video_filter`: `denoise` (hqdn3d) and `deinterlace` (yadif). *(Shipped in v0.4.0)*
- [x] **Smarter GIF output** — Quality-based scaling (low=320, medium=480, high=640, ultra=800) instead of fixed 480px. *(Shipped in v0.4.0)*
- [x] **Rich CLI output** — Human-friendly terminal UI with tables, spinners, styled error panels. `--format json` for scripts. `--version` flag. Video templates (TikTok, YouTube Shorts, Instagram Reel, YouTube, Instagram Post). *(Shipped in v0.4.0)*

- [x] **Crop by percentage** — `video_crop` supports `crop_percent` (e.g. 50 for center 50%).
- [x] **Orientation-aware metadata** — `video_info` returns `rotation`, `display_width`, `display_height`, `display_resolution`, and `aspect_ratio`.
- [x] **Merge auto-concat** — `video_merge` auto-normalizes resolution, codec, fps, and audio sample rate mismatches.
- [x] **convert vs export clarity** — Docstrings updated: `video_convert` for format/codec changes, `video_export` for final delivery re-encoding.
- [x] **Template preview** — `video_template_preview` returns operations list, estimated duration, resolution, and size without rendering.
- [x] **Batch operations** — Accept multiple inputs for a single operation. "Trim these 5 videos to 10 seconds each" in one call instead of 5. *(Shipped in v0.3.0 as `video_batch`)*

## Low Impact (Nice to have)

- [x] **Custom font upload** — `font_manager.py` downloads and caches Google Fonts by name for use in text overlays. *(Shipped in v1.3.0)*
- [x] **Video concatenation with transitions per-clip** — Already supported in `merge` via `transitions` parameter; `video_edit` sequence shortcut accepts `clips` + `transitions` + `transition_duration` (expanded via `expand_sequence_shortcut`).
- [x] **Audio waveform extraction** — Return a text-based waveform representation so agents can "see" the audio without playing it. Useful for finding silence or loud sections. *(WaveformResult.text ASCII via _render_ascii_waveform)*
- [x] **Subtitle generation from text** — Given a list of `[(start, end, text)]` tuples, generate an SRT file and burn it in one step. *(Shipped as `video_generate_subtitles`)*
- [x] **Frame-accurate seeking** — Use `-ss` before `-i` (input seeking) for speed, but fall back to output seeking for frame accuracy when the user specifies exact timestamps. *(trim accurate=True + te/seek helpers)*
- [x] **Output directory option** — Currently outputs go next to the input file. Add a global `output_dir` option so all intermediates go to a temp folder. *(Shipped in v0.3.0 as `video_batch --output-dir` / `output_dir` param)*

## Observability (For you as the maintainer)

- [~] **Usage analytics** — Dropped 2026-06-12. A v1.3.0 agent commit shipped a ping module pointing at a Vercel endpoint that was never deployed or owned; removed because an unowned, claimable domain receiving install IDs is a liability, not observability. If telemetry ever returns it needs an endpoint we actually control, decided first.
- [x] **Structured logging** — Currently silent on success. Add a `--verbose` flag and optional log file. Helps users debug their own issues before filing them. *(`-v/--verbose` + `--log-file PATH`)*
- [x] **GitHub Actions CI** — Run the full test suite on push. Catch regressions before they ship. Currently manual. *(Shipped in v0.2.x)*

## Not Doing (Intentionally out of scope)

- **Streaming** — RTMP, HLS output. Different domain.
- **GPU acceleration** — Keep it simple. CPU FFmpeg is fast enough for the target use case.

## FFmpeg Coverage Gaps

Features that FFmpeg supports but Kinocut doesn't expose yet. Ordered by impact.

### High Impact
- [x] **Audio effects** — Reverb (`aecho`), equalizer (`equalizer`), compressor (`acompressor`), pitch shift (`asetrate`+`aresample`), noise reduction (`afftdn`)
- [x] **Video stabilization** — Deshake filter (`vidstab`) for shaky handheld footage (requires FFmpeg with vidstab)
- [x] **Scene detection** — Auto-detect scene changes using `select` filter, return timestamps
- [x] **Quality metrics** — PSNR, SSIM, VMAF calculation for comparing video quality

### Medium Impact
- [x] **HLS/DASH streaming** — `hls_segment()` segments video into HTTP Live Streaming format with multi-quality variants. *(Shipped in v1.3.0)*
- [x] **Advanced codecs** — `convert()` now supports `hevc` (H.265), `av1`, and `prores` output formats. *(Shipped in v1.3.0)*
- [x] **Image sequences** — Create video from image sequences (`img2pipe`), export frames
- [x] **Metadata editing** — Read/write video metadata tags, chapter support
- [x] **Audio waveform extraction** — Text-based waveform for silence/loud section detection
- [x] **Subtitle generation** — Generate SRT from `[(start, end, text)]` tuples, burn in one step *(Shipped as `video_generate_subtitles`)*

### Low Impact
- [x] **Ken Burns / zoom pan** — Animated zoom/pan effects via `zoompan` filter
- [x] **Advanced masking** — New `luma_key()` (brightness-based masking) and `shape_mask()` (circle, rounded_rect, oval) tools. *(Shipped in v1.3.0)*
- [x] **Frame-accurate seeking** — Input seeking for speed, output seeking for accuracy *(trim accurate=True)*
- [x] **Two-pass encoding** — More efficient compression for target file sizes
