# Changelog

All notable user-facing changes should be recorded here.

This project follows a simple release-note style:

- `Added` for new capabilities.
- `Changed` for behavior changes.
- `Fixed` for bug fixes.
- `Security` for vulnerability fixes.

## Unreleased

### Fixed

- Audio-only normalization now uses an audio-aware output probe, so valid WAV results no longer fail with a misleading `No video stream found` error. Audio muxing continues to validate audio inputs without video-only warnings.
- Hyperframes commands normalize a project path once at command entry, preventing relative paths such as `hyperframes` from resolving as `hyperframes/hyperframes`.
- `audio-compose` now decodes supported non-legacy WAV containers, including `WAVE_FORMAT_EXTENSIBLE`, to canonical mono signed 16-bit PCM at the requested sample rate before mixing.
- Technical and design quality checks now report shared saturation and contrast metrics with explicit units and availability. `video-quality-check --fail-on-warning` exits nonzero whenever the returned result has `all_passed: false`.
- Rescue acceptance fixtures now encode rotation with stream metadata supported by the Bookworm CI image, so the push-only slow suite runs against its installed FFmpeg instead of failing during fixture creation.

### Added

- **Post-rescue planning capabilities** - eight matching MCP, CLI, and Python client
  surfaces now expose source-backed semantic timelines and local query, reviewable timeline
  edit plans, subject-aware visual transforms, evidence-gated restoration, source-backed
  composition, capability-gated creative autopilot, and explicit remote egress contracts.
  These calls plan or verify only: they do not render, download models, submit remote jobs,
  or silently broaden an approval. See `docs/POST_RESCUE_FEATURES.md`.

- **Rescue R1 extension contracts** - immutable, versioned policy profiles; separately
  hashed feature-intent envelopes; additive verifier and capability registries; and
  deterministic preview/approval bindings now let new editing features reuse the rescue
  safety kernel without changing rescue v1 plans, receipts, hashes, or behavior.
- **Dedicated video rescue pipeline** - three additive MCP tools
  (`video_rescue_plan`, `video_rescue_render`, `video_rescue_inspect`), CLI commands
  (`rescue-plan`, `rescue-render`, `rescue-inspect`), and Python client methods now diagnose
  one local video, classify repair candidates, render approved safe IDs, and inspect a
  verified rescue package. Every successful video rescue includes a master, universal
  sharing copy, hashed receipt, and optional caption/transcript sidecars or explicit
  unavailable reasons. See `docs/RESCUE.md`.
- **Rescue FFmpeg portability gate** - the pinned FFmpeg 6/7/8 CI matrix now exercises the
  public rescue plan/render/inspect path, MOV/WebM sharing copies, and reproducible render
  contracts in addition to compositor and workflow filtergraphs.
- **`composite_layers` workflow op** — the workflow engine's allowlist grows to **7 ops**;
  a step may now compose an ordered layer stack (`op: "composite_layers"`) without leaving
  the workflow's safety envelope. Layer sources are expressed as workflow `@refs`
  (`inputs.layers[].src` / `.mask` → `@sources.<id>` / `@work/<name>`), never as nested or
  raw paths (those fail closed with `unsafe_workflow_source`). Every layer source is
  resolved, workspace-confined, and hashed into the step's `input_hashes` (one sha256 per
  layer source), and the workflow layer synthesizes a workspace-confined nested spec that
  the vetted `composite_layers` engine consumes — so composite provenance matches every
  other op. The only tunable param is `canvas`; output uses the normal
  `@work`/`@outputs` binding + `output_hash`. This rides the existing `video_workflow_*`
  tools / `workflow-*` CLI (no new tool or command). See `docs/WORKFLOWS.md`.

### Safety

- Rescue is local-only, source-immutable, and timeline-locked. Plan/source/policy/dependency
  staleness and invalid approvals fail closed; cancellation never promotes output;
  verification failures are quarantined; resumable intermediates require matching hashes;
  and all promoted artifacts have receipt hashes and explicit verification metrics/units.
  Captions remain sidecars and rescue never downloads Whisper or invokes cloud processing.

### Compatibility

- Existing MCP, CLI, and Python APIs are unchanged. Whisper remains optional, the universal
  sharing copy is additive to the high-quality master, and intentional 24 fps delivery
  behavior elsewhere in MCP Video is unchanged.

### Security

- **Workflow artifact writes are confined to the spec's workspace root (R1)** — `--save-plan`,
  `--save-receipt`, and `--save-receipt-dir` now additionally require the resolved target to
  live UNDER the spec's workspace directory (the same realpath + `relative_to` confinement
  every declared source and output already obeys), on top of the existing
  traversal/symlink/system-dir/dotfile guard. A `.json` write that passed the media guard but
  pointed outside the workspace now fails closed with `unsafe_workflow_source`.
- **Out-of-workspace absolute paths redacted in workflow errors (R2)** — a wrapped engine
  fault whose message embeds an absolute home path (`/Users/<name>/…`, `/home/<name>/…`)
  outside the workspace is now redacted to `<redacted-path>` in both the raised
  `MCPVideoError` and the receipt's recorded step error, closing a residual path leak beyond
  the workspace-prefix strip.

## 1.6.0 - 2026-07-09

### Added

- **Agent workflow engine** — a new `video_workflow_*` MCP tool family (`video_workflow_validate`, `video_workflow_plan`, `video_workflow_render`, `video_workflow_inspect`) plus flat CLI commands (`workflow-validate`, `workflow-plan`, `workflow-render`, `workflow-inspect`) and Python client parity (`Client.workflow_validate/plan/render/inspect`). An agent can define a multi-step local video job as a JSON spec (`schema_version: 1`), validate it cheaply, produce a no-render dry-run plan, render it with a provenance receipt, and inspect that receipt afterward. Steps are an ordered, backward-reference-only list over a fixed 6-op allowlist (`probe`, `trim`, `resize`, `convert`, `merge`, `add_text`), each backed by an existing vetted engine; unknown ops, forward/unknown `@refs`, and workspace-escaping paths fail closed with `MCPVideoError` codes.
- **Workflow resume, variants, and cleanup** — `video_workflow_render --resume <receipt>` continues a partially-completed job (spec-hash gated; a step is reused only when it is completed AND its output and input hashes still match); `variants[].overrides` emit N outputs from one source/step declaration; intermediates in the job's isolated `@work/` directory are cleaned on success, kept on failure, and `--keep-intermediates` overrides cleanup for inspection.
- **Compositor full-canvas blend modes** — `composite-layers` / `video_composite_layers` layers accept `blend` values `multiply`, `screen`, `overlay`, `darken`, `lighten`, applied full-canvas via the FFmpeg `blend` filter. Positioned/scaled/masked/timed blend is deferred and fails closed with the new `unsupported_blend_geometry` code; unknown modes fail closed with `unsupported_blend_mode`.
- **Compositor rotation and pivot** — layers accept `rotation` (degrees, transparent-fill) and a new `pivot` field (`center` default, plus the four corners) setting the rotation/placement reference point. The existing `anchor` position alias is unchanged. Unknown pivots and non-numeric rotation fail closed.
- `composite-layers` / `video_composite_layers` P2 supports transform sizing, timing windows, mask/matte alpha sources, dry-run layer plans, source/output hashes, and richer render receipts for agent review before publishing.
- `video_duck_audio`: mix background music under a video's voice with automatic sidechain ducking — the music dips during speech and recovers in pauses. Engine function `duck_audio` with validated `music_volume`, `threshold`, `ratio`, `attack`, and `release` parameters.
- `video_ai_color_grade` accepts `lut_path` for professional `.cube`/`.3dl` LUT files via FFmpeg `lut3d`, overriding style presets and reference matching.
- `video_convert` streams MCP progress notifications during long renders, so clients can show a live percentage instead of an apparently hung call.
- Spanish-language README section (`En español`) and bilingual EN/ES text for the most common errors (FFmpeg missing, file not found).
- New docs for the release surface: `docs/WORKFLOWS.md` (workflow engine), workflow + layer_plan receipt schemas in `docs/VIDEO_RECEIPT.md`, and a receipt-privacy scan test that fails on any home path, username-in-path, or secret-shaped token in committed docs/examples or freshly produced dry-run/render artifacts.

### Changed

- **`layer_plan` receipt bumped to `schema_version: 2`** (backward-readable, additive). It gains a `receipt_kind` discriminator (`"layer_plan"`), `transform.rotation`/`transform.pivot` fields, blend/rotation `features` flags, and an explicit `audio_policy: "dropped_video_only"` flag (composite output stays video-only this release; audio compositing is deferred, documented, and receipt-flagged rather than silent). `video_workflow_inspect` reads both new workflow receipts and legacy `receipt_kind`-less v1 layer_plan receipts by inferring the kind.
- Glitch tools (`glitch_rgb_shift`, `glitch_scanline_jitter`, `glitch_screen_tearing`, `glitch_vhs_tracking`, `glitch_macroblocking`, `glitch_datamoshing`, `glitch_cmyk_split`, `glitch_turbulent_displacement`) now return rich edit metadata in their MCP responses — `duration`, `resolution`, `size_mb`, and `elapsed_ms` — matching the envelope shape of all other edit tools. Previously these tools returned only `success` and `output_path`.

### Fixed

- The `composite-layers` layer-plan receipt now records `output_path` (and `resolved_src`/`mask`) relative to the spec directory whenever the file lives inside it, instead of emitting the resolved absolute path — a shared or committed receipt no longer leaks the user's home directory. Internal rendering still uses the resolved absolute location; only the receipt is relativized.
- Removed BasicPitch from declared optional extras and documented it as a manual integration so Dependabot can patch vulnerable TensorFlow/Keras/protobuf transitive dependencies instead of resolving an unsafe pinned stack.

### Security

- **Workflow param VALUE validation** — a step's `params` values are now type-checked against the backing engine's parameter types (not just names), so a string for an integer parameter (e.g. `width="20000"`, `size="24,drawtext=textfile=/etc/hosts"`) fails closed with `invalid_workflow_params` before any FFmpeg invocation. Engine sinks are independently hardened: `resize` rejects non-integer/oversize dimensions and `add_text` coerces `fontsize` through a numeric guard before filtergraph interpolation.
- **Workflow artifact write-path validation** — `--save-plan`, `--save-receipt`, and `--save-receipt-dir` now route through the same traversal/symlink/system-directory/sensitive-dotfile guard as media outputs and additionally refuse to overwrite any file that is not a `.json` artifact, closing an arbitrary out-of-workspace overwrite that previously only rejected null bytes.
- **Workflow resource caps** — a spec may declare at most 64 steps and 32 variants, and `resize` dimensions are bounded to 7680px; exceeding a cap fails closed.
- **`add_text` `font` excluded from workflow specs** — the path-typed `font` parameter (a filesystem existence oracle) is no longer tunable through a workflow op and fails closed as an unaccepted param; set fonts by calling `add_text` directly.
- Workflow steps now fail closed on ANY engine exception (not only `MCPVideoError`): an unexpected runtime fault is wrapped as `workflow_step_failed`, recorded on the receipt with a workspace-sanitized message, and left resumable; the Python client rejects a dict spec for render; batch variants that resolve to a colliding output path fail closed; and raw-relative input refs are re-confined to the workspace at execution time (closing a validate→execute symlink TOCTOU).

### Removed

- The opt-in anonymous analytics ping (`MCP_VIDEO_ANALYTICS=1`). The endpoint it posted to was never deployed or owned by the project, making the domain claimable by a third party — removed entirely rather than left as a silent no-op.
- `video_generate_music` and the MiniMax music API integration. A hosted, per-key music API does not belong in a local-first tool; background-music generation moves to a local open-source pipeline (planned: ACE-Step) with mcp-video handling the mixing via `video_duck_audio`.

## 1.5.2 - 2026-07-06

### Added

- Added `composite-layers` / `video_composite_layers` P1 for ordered image/video/solid layer stacks with normal alpha compositing, per-layer opacity, fixed x/y placement, and deterministic layer-plan receipts.
- Added Python client parity for `Client.composite_layers(...)`.

### Changed

- Routed Forgejo CI required jobs to the known-live `light` runner label so PR and post-merge checks do not wait on optional heavyweight runners.
- Aligned package metadata with the Forgejo repository as the canonical source while preserving MCP Registry identity.

### Fixed

- Guarded glitch shader ffprobe subprocess calls with timeout-aware error handling.
- Removed tracked local `.pi-lens` cache artifacts and scrubbed public local-infrastructure references from agent guidance files.
- Added release-hardening checks to prevent local path/cache leakage from returning.

## 1.5.1 - 2026-06-04

### Fixed

- Removed the unpublished `meltysynth` dependency from optional audio extras so Glama, uv, and package metadata validators can resolve the project.
- Updated the repository readiness audit after the intentionally removed `/explainer-video` npm Dependabot entry.

## 1.5.0 - 2026-06-04

### Added

- Added Video Receipt documentation for agent-created media review trails.
- Added receipt-backed confidence baseline workflow with quality report, release checkpoint, storyboard, thumbnail, and pending human-review status.
- Added local repurpose-package workflow for platform variants with manifest, review artifacts, checkpoints, and receipt output.
- Added confidence benchmark and adversarial certification scripts for local readiness proof.
- Added dated proof notes for fresh install confidence, public issue triage, agentic media readiness, and external feedback asks.

### Changed

- Hardened the explainer workflow into a 10-stage receipt-producing lane with transition audit records, audio normalization, quality report, and a real `min_score=50` release checkpoint.
- Updated workflow routing docs and golden workflow map around the confidence proof lanes.

### Fixed

- Removed the stale Dependabot `/explainer-video` npm configuration entry so dependency automation can run against real package paths.
- Made corrupted media probing fail as `InputFileError`, giving adversarial checks a clear invalid-input signal.
- Fixed the confidence benchmark so stale receipts cannot hide a failed workflow run.

## 1.4.1 - 2026-05-25

### Added

- Added preflight guardrails for high-risk video/audio edit paths:
  - `video_filter` warns and clamps out-of-range filter parameters.
  - `video_merge` warns on resolution/FPS/audio mismatches and rejects transitions longer than the shortest clip.
  - `video_add_audio` validates volume and warns on mix/timing risks.
  - `video_overlay`, `video_watermark`, and `video_chroma_key` validate opacity/similarity/blend/timing parameters.
  - `video_text_animated` validates color, start/duration, and warns on timing/overflow risks.
  - `video_layout_grid` and `video_split_screen` warn on clip-count, duration, FPS, and audio mismatches.
- Added tracked implementation plan at `docs/plans/2026-05-24-video-guardrails.md`.

### Changed

- Refreshed README, tool reference, landing page, roadmap, contribution guide, package metadata, and GitHub repository description for the current 119-tool guardrailed surface.

## 1.4.0 - 2026-05-09

### Added

- Expanded Hyperframes orchestration for the 0.5 surface: snapshots, inspection, metadata, catalog, website capture, local TTS, transcription, background removal, diagnostics, benchmarks, and richer render controls.
- Added local video repurposing helpers for dry-run manifests and platform-ready variants with thumbnails, storyboards, and optional release checkpoints.
- Real `analyze_video(include_colors=True)` color extraction — returns actual dominant colors instead of placeholder values.
- `video_info_detailed` now returns real dominant colors instead of `None`.

### Changed

- Refreshed README, MCP tool docs, Python client docs, AI discovery, and `llms.txt` so PUSHING CREATION, Hyperframes, and repurposing are described as the current operator paths without centering test-count messaging.
- Pipeline cleanup `OSError`s are now surfaced as warnings instead of being silently swallowed.

### Fixed

- Fixed green-cast video effects and 24-bit WAV handling in `effect_noise`, `video_overlay`, and audio effects.
- Fixed 24-bit WAV handling in `audio_compose`.
- Design quality probe now returns `None` on analysis failure instead of sentinel values (128 luma, 50 contrast) that produced perfect scores.
- Typography check adds an advisory issue when brightness analysis is unavailable.
- Reject unsupported Hyperframes render dimensions instead of silently accepting them.
- Report Hyperframes render artifacts correctly by output format, including `png-sequence` directories.
- Fail Hyperframes render-and-post/pipeline paths when render artifacts are missing.
- Reject unknown text animations instead of silently ignoring them.
- Reject empty animated text at engine and MCP/tool layers.
- Reject invalid layout/PIP choices at tool and engine boundaries.
- Validate mograph duration/fps/style and reject unknown progress style.
- Reject unknown animated text positions.
- Reject unknown watermark/overlay positions.
- Reject malformed timeline image overlay position dicts before input probing.
- Validate convert format/quality before probe/FFmpeg.
- Validate HLS qualities and segment duration before probe/FFmpeg.
- Reject unsupported `compare_quality` metrics instead of reporting meaningless `unknown`.
- Validate `video_batch` operation names before input path validation.
- Validate malformed subtitle entries/ranges before input path validation.
- `audio_compose()` rejects missing track files, empty tracks, non-dict entries, non-positive duration, and invalid volume.
- `audio_sequence()` rejects unknown/missing event types and unsupported tone waveforms.
- `audio_effects()` rejects unknown/missing effect types.
- `audio_preset()` rejects invalid pitch and intensity.
- `audio_synthesize(effects={...})` rejects unknown effect keys.

## 1.3.10 - 2026-05-07

### Fixed

- Improved `mcp-video doctor` guidance on Python 3.13+ so missing Real-ESRGAN/BasicSR reports explain the BasicSR build guard and point users to the OpenCV fallback or Python 3.11/3.12 for the Real-ESRGAN backend.

## 1.3.9 - 2026-05-06

### Fixed

- Fixed `mcp-video[all-ai]` and `mcp-video[upscale]` installs on Python 3.13 by guarding Real-ESRGAN/BasicSR dependencies behind the Python versions where BasicSR still builds, while keeping the OpenCV upscaling fallback installable.

## 1.3.8 - 2026-05-06

### Fixed

- Fixed AI scene-detection JSON output so perceptual-hash differences are serialized as standard JSON numbers.
- Added `torchcodec` to stem-separation extras and diagnostics so Demucs output works with current TorchAudio save behavior.

## 1.3.7 - 2026-05-06

### Fixed

- Fixed `search_tools()` / `Client.search_tools()` so discovery includes the full 91-tool MCP surface, including PUSHING CREATION, Hyperframes, audio, and AI tools.

## 1.3.6 - 2026-05-06

### Added

- Added PUSHING CREATION-compatible cinematic pre-production tools:
  - `video_project_create`
  - `style_pack_read`
  - `storyboard_read`
  - `shot_prompt_render`

### Changed

- Updated package, MCP registry metadata, README, `llms.txt`, and tool docs for the 91-tool cinematic creation surface.
- Toned down public launch copy so test coverage is supporting evidence rather than the main product message.

### Fixed

- Restored README readiness anchors required by the repository audit.

## 1.3.1 - 2026-05-03

### Security

- Fixed command injection risk in `engine_stabilize.py` — vectors file path now validated as absolute.
- Enabled SSL certificate verification for AI model downloads in `ai_engine/upscale.py`.
- Redacted full filesystem paths from stabilization error messages.

### Fixed

- Added proper AI operation timeout (3600s) for demucs/whisper — prevents premature kills on long videos.
- Increased FFmpeg stderr buffer from 1MB to 10MB — fixes truncated progress for long-running operations.
- Fixed temp file leak in typewriter text effect — cleanup now happens even on write failure.
- Added `OSError` handling in hyperframes for file size race conditions.
- Added pitch shift semitones range validation (-48 to +48) — prevents FFmpeg filter chain overflow.
- Capped pixel count in color extraction (50K max) — prevents memory exhaustion on large images.
- Added try-finally cleanup for Whisper temp WAV files.
- Added bitrate/size range validation in probe before integer conversion.
- Added 1MB JSON size limit in CLI argument parser.
- Added `threading.Lock` for thread-safe probe cache.
- Centralized all timeout constants in `limits.py`.

### Changed

- Standardized tool count to **87 MCP tools** across all documentation and metadata files.
- Removed duplicate Hyperframes Integration section from README.
- Removed duplicate architecture entry from README.
- Documented `video_cleanup` tool in TOOLS.md.
- Updated test count in TESTING.md.
- Marked shipped v1.3.0 features as completed in ROADMAP.md.
- Updated server.json version to 1.3.1.

### Removed

- **Remotion integration completely removed.** All Remotion MCP tools, CLI commands, client methods, engine modules, and tests have been deleted. The project now uses Hyperframes (HTML-native, Apache 2.0) as its sole code-based video creation engine.
  - Deleted: `mcp_video/remotion_engine.py`, `mcp_video/remotion_models.py`, `mcp_video/server_tools_remotion.py`, `mcp_video/client/remotion.py`, `mcp_video/cli/handlers_remotion.py`, `mcp_video/cli/parser/remotion.py`, `tests/test_remotion_engine.py`, `tests/test_remotion_deprecation.py`
  - Removed `RemotionNotFoundError`, `RemotionProjectError`, `RemotionRenderError` from `errors.py`
  - Removed `VALID_REMOTION_TEMPLATES` from `validation.py`
  - Removed Remotion category from `doctor.py` checks
  - Updated `test_public_surface.py`: 87 MCP tools (was 93), 88 CLI commands (was 94)
  - Removed `remotion` optional dependency, pytest marker, and keyword from `pyproject.toml`
  - Removed Remotion CI smoke test job
  - Updated all documentation to remove Remotion references

### Design

- Redesigned landing page: Space Grotesk + DM Sans typography, orange/teal video-editing palette.
- Fixed broken mobile menu with proper responsive CSS.
- Added inline SVG favicon, ARIA labels, skip-to-content link.
- Improved hero headline: "87 Video Tools. Zero Cloud Costs."
- Added Organization schema markup for better SEO.
- Optimized font loading with preconnect hints.

## 1.3.0 - 2026-04-28

### Added

- **Crop by percentage** — `crop()` now accepts `crop_percent` (e.g. `crop_percent=50` for a center 50% crop). Alternative to explicit `width` + `height`.
- **Orientation-aware metadata** — `VideoInfo` now exposes `rotation`, `display_width`, `display_height`, and `display_resolution`. ffprobe `side_data_list` is parsed for rotation metadata.
- **Audio waveform text representation** — `WaveformResult.text` returns an ASCII art waveform for agent-friendly display.
- **Frame-accurate seeking** — `trim()` gains `accurate=True` for output-seeking (slower, frame-perfect) vs the default fast input-seeking.
- **Pipeline output cleanup** — `Client.pipeline()` gains `cleanup=True` to auto-remove intermediate files after chaining.
- **Structured logging** — New `--verbose` / `-v` CLI flag enables DEBUG logging to stderr.
- **Template preview** — `preview_template()` returns operations list + estimated output before rendering a timeline template.
- **Custom font upload** — `font_manager.py` downloads and caches Google Fonts by name for use in text overlays.
- **Usage analytics** — `analytics.py` sends an optional anonymous ping on server startup. Disable with `MCP_VIDEO_ANALYTICS=0`.
- **HLS/DASH streaming** — `hls_segment()` segments video into HTTP Live Streaming format with multi-quality variants.
- **Advanced codecs** — `convert()` now supports `hevc` (H.265), `av1`, and `prores` output formats.
- **Advanced masking** — New `luma_key()` (brightness-based masking) and `shape_mask()` (circle, rounded_rect, oval) tools.
- **Smarter GIF output** — Quality-based fps scaling (10/12/15/20), Bayer dithering, and 128-color palette generation.

### Changed

- **Merge auto-normalize** now handles fps mismatches, audio sample rate mismatches, and rotation-aware display dimensions during normalization.
- **Remotion deprecation upgraded** from `DeprecationWarning` to `FutureWarning` for v1.3.0 timeline.
- Public tool count updated from 90 to **87** unique MCP tools.

### Fixed

- `convert()` vs `export_video()` docstrings clarified to distinguish format changes from quality-tuned delivery.

## 1.2.6 - 2026-04-27

### Changed

- Bumped version to 1.2.6 (1.2.5 tag already existed).

## 1.2.5 - 2026-04-27

### Added

- **Hyperframes integration** — 8 new MCP tools, Python client methods, and CLI commands for HTML-native video creation:
  - `hyperframes_init` — scaffold new projects (blank, warm-grain, swiss-grid templates)
  - `hyperframes_render` — render compositions to MP4/WebM/MOV
  - `hyperframes_still` — render single frames via snapshot
  - `hyperframes_compositions` — list compositions in a project
  - `hyperframes_preview` — launch live preview studio
  - `hyperframes_validate` — validate project structure and run lint
  - `hyperframes_add_block` — install blocks from the Hyperframes catalog
  - `hyperframes_to_mcpvideo` — render then post-process with mcp-video in one step
- Full test suite for Hyperframes engine: 54 unit + integration tests in `tests/test_hyperframes_engine.py`.
- `sample_hyperframes_project` pytest fixture.

### Changed

- **Remotion is deprecated.** All Remotion MCP tools, client methods, and CLI commands now emit `DeprecationWarning`. Remotion will be removed in a future major version. Migrate to Hyperframes (Apache 2.0) or Revideo (MIT).
- Public tool count updated from 82 to 90 unique MCP tools.
- `mcp_video/client/remotion.py` — all methods now warn on usage.

### Fixed

- `hyperframes_engine.validate()` no longer raises `HyperframesProjectError` when no HTML entry point is found; it correctly reports the issue in the validation result.

## 1.2.4 - 2026-04-22

### Added
- `Client.subtitles_styled()` alias for `text_subtitles()` to match MCP tool rename.
- Runnable `workflow.py` for `02-podcast-clip` (6 stages).
- Runnable `workflow.py` for `03-explainer-video` (7 stages, client-only, no raw FFmpeg).

### Changed
- Documentation updated for `search_tools`, `workflows/`, and ICM alignment.
- `workflows/01-social-media-clip/workflow.py` fixed client arg names.

## 1.2.3 - 2026-04-22

### Changed

- Consolidated duplicate tools: removed `video_blur`, `video_color_grade`, and `video_extract_frame` as standalone tools. Functionality preserved through `video_filter` and `video_thumbnail`.
- Renamed `video_text_subtitles` to `video_subtitles_styled` for clearer naming.
- Added `search_tools` meta-tool for fast tool discovery by keyword.
- Updated public tool count from 83 to 81 unique tools.
- Reorganized docs/TOOLS.md into 12 functional categories.

### Fixed

- Image analysis tools (`image_extract_colors`, `image_generate_palette`, `image_analyze_product`) now accept video input by auto-extracting a representative frame.

### Added

- Added ICM-style `workflows/` directory with 3 production-ready pipelines: social-media-clip, podcast-clip, and explainer-video.
- Added `CLAUDE.md` and `workflows/CONTEXT.md` for agent context routing.

## 1.2.2 - 2026-04-21

### Added

- Added GitHub Discussions templates, CODEOWNERS, maintainer/governance docs, and Dependabot configuration.
- Added `llms.txt`, `robots.txt`, `sitemap.xml`, and `server.json` for search, AI-agent discovery, and MCP Registry readiness.
- Added `docs/AI_AGENT_DISCOVERY.md` and an adversarial remediation plan.
- Added `_validate_output_path()` and rolled it out across all engines for safer output directory handling.
- Added client-side validation and return type annotations for improved API contract consistency.
- Added current edge-case audit document (`docs/CURRENT_EDGE_CASE_AUDIT_2026-04-21.md`).

### Changed

- Updated public tool count messaging from 82 to the current 83 MCP tools.
- Updated the landing page with crawl metadata and structured software/source metadata.
- Normalized root metadata links to the canonical repository URL.
- Replaced the grey social preview image with generated media artwork.

### Security

- Fixed TOCTOU race conditions and sanitized numeric values in FFmpeg filters.
- Hardened AI engine resource guards for scene detection, spatial audio, stem separation, transcription, and upscaling.
- Hardened direct download paths with timeout and size limits.
- Closed top-priority audit validation gaps across engine boundaries.
- Fixed design quality security and SRT format safety issues.

### Fixed

- Added startup validation to `remotion_engine.studio()` to catch immediate process crashes.

## 1.2.1 - 2026-04-13

### Changed

- Prepared the 1.2.1 package metadata and public badge.
- Improved runtime error contracts and diagnostics.
- Repaired repository trust rails for deploys, packages, tests, and AI extras.

### Fixed

- Aligned `mcp_video.__version__` with the package version in `pyproject.toml`.
- Moved optional dependency metadata out of Ruff configuration.
- Centralized chroma-key color validation for safer FFmpeg filter construction.

## 1.2.0 - 2026-03-31

### Added

- Published the 1.2.0 package release.
- Documented the broad MCP, CLI, Python client, FFmpeg, Remotion, image, audio, AI, and quality-guardrail surface.
