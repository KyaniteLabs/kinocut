# MCP Tools Reference

Every Kinocut MCP tool, what it does and how to reach it. Every tool returns structured
JSON with `success`. A failure returns `{"success": false, "error": {...}}` ending in the
exact MCP and CLI retry call.

## How tools are listed

| `KINOCUT_TOOLS` | Tools listed | What you get |
| --- | --- | --- |
| unset (default) | 18 | 8 hot-path tools, 8 operation families, `list_operations`, `describe_operation` |
| `profile:<name>` | varies | the default 18 plus one job's tools by name (`profile:editor` lists 115) |
| `all` | 206 | every tool by its own name; families hidden |

Kinocut 1.16.5 listed 20 tools by default and 205 with `all`; 2.0.0 lists the numbers
above. The hot path is `video_info`, `video_trim`, `video_merge`,
`video_add_text`, `video_add_audio`, `video_extract_frame`, `video_shorts` and
`video_doctor`. Every other tool is an operation inside one family; see
[MCP_TOOL_FAMILIES.md](MCP_TOOL_FAMILIES.md).

## Quick start for agents

1. Inspect with `video_info` (CLI `kino info`). Run `video_doctor` (`kino doctor`) before
   a long job.
2. If the hot path lacks the operation, call `list_operations` with a family or a query,
   then `describe_operation` for its full schema, then call the family with
   `{"operation": ..., "params": ...}`.
3. Write to an explicit new output path, read the result and receipt, run the quality
   checks, and ask a person to review before anything is published.

The sections below explain the main tool groups. The [complete index](#complete-index)
at the end lists all 206 tools.

---

## Output overwrite policy

MCP calls accept a strict boolean `overwrite` parameter, defaulting to `false`.
An existing output requires an explicit `overwrite=true`. This allows replacing
existing media; pre-existing JSON, text, CSV, TypeScript and other non-media files
stay protected. Non-media output can only be replaced when Kinocut created the
current file in the same job, with consent. Hermes and other agent configuration
homes remain protected even with consent. Source/output alias guards still apply.
Prefer a new output path. Python client calls accept the same `overwrite=True`
keyword; the CLI uses `kino --overwrite COMMAND ...`.

Use an output directory with one writer at a time. The overwrite checks do not
guarantee preservation against another process replacing a target between
validation and publication. Atomic receipt updates retain complete old-or-new
JSON; do not run competing jobs against the same output or receipt paths.

### Upgrading existing jobs

Finish existing workers with their original runtime before switching versions.
Durable render receipts and shorts plans now retain inode ownership evidence in
hidden `.<filename>.ownership` directories. Legacy jobs without this evidence
cannot be resumed or updated by the new runtime; start a new job instead of
adopting the old receipt. Preserve ownership directories with their jobs, and
verify restart after any backup or move: copying visible JSON alone, or a copy
that changes hard-link relationships, loses the proof. Historical receipt inodes
remain retained; this release does not prune them automatically.

Publication and durable ownership require filesystem hard-link support. Use a
supported local filesystem and verify it before a long job. Network, cloud-sync
and removable filesystems are not assumed compatible; do not bypass a failed
publication check with a direct file copy.

## Project-backed Inspection

These operations share one adapter with the Python client and CLI. Only ingest accepts a
host source path. Later operations resolve the active stored record by `asset_id`; they do
not accept a caller-supplied record or an arbitrary media path.

| Tool | Description |
|------|-------------|
| `video_ingest` | Copy source bytes into a content-addressed private project and return the authoritative asset record |
| `video_preflight` | Persist one technical, loudness, color, and full-decode report for a stored asset |
| `video_inspect_temporal` | Persist sampled frames, a motion strip, frame differences, deterministic findings, explicit optional-provider availability, and the complete inspection manifest |

`video_preflight` and `video_inspect_temporal` require an existing project. Optional visual
providers are not contacted or downloaded implicitly; the default result explicitly marks
both visual capabilities unavailable.

## Durable Intent and Recipe Tools

These tools operate on an existing project, edit project, and immutable revision. Semantic
search stays local and revision-bound. Recipe export verifies that caller-supplied operation
descriptors compile to the selected revision, then emits a canonical artifact containing
digest placeholders and typed parameters—not host paths. Replay requires explicit source
digest bindings and appends a new revision; it never overwrites the source or publishes.

| Tool | Description |
|------|-------------|
| `video_find_moments` | Persist or query a bounded, revision-owned semantic index in projectstore CAS |
| `video_project_recipe_export` | Export a verified revision path as a path-free, policy-carrying portable recipe |
| `video_project_recipe_replay` | Bind recipe source slots to explicit CAS digests and replay into a durable revision |

The guarded recipe flow is: review the source revision and policies, export, distribute the
JSON artifact, bind every `cas_digest` slot in the destination project, then replay. A recipe
is not release authority: review gates remain metadata that the receiving workflow must
satisfy, and no tag, package upload, directory submission, or publish action occurs.

## Governed AI-video Review and Salvage

These operations share one validated boundary with the Python client and CLI. Protection
has no force or bypass parameter; authorization accepts only stored human decision ids.
The end-to-end sequence and stop conditions are in
[AI_VIDEO_REVIEW_AND_SALVAGE.md](AI_VIDEO_REVIEW_AND_SALVAGE.md).

| Tool | Description |
|------|-------------|
| `video_verdict` | Persist exact-asset analysis; approved dispositions require an active exact human decision and requirement-level evidence |
| `video_acceptance_eval` | Resolve active stored spec/verdict ids and derive acceptance without creating an approval |
| `video_body_swap` | Require a project and two active stored inputs, then replace video while preserving approved audio |
| `video_salvage` | Create one content-addressed, lineage-bound salvage derivative with a fresh non-approved review slot |

---

## Discovery

| Tool | Description |
|------|-------------|
| `list_operations` | Default surface. Lists a family's operations (or matches a `query`) with verb, required parameters and declared annotations. |
| `describe_operation` | Default surface. Returns one operation's complete `inputSchema` and the family call that runs it. |
| `search_tools` | Listed with `all` or `profile:editor`. Ranks registered tools by exact name, keyword or task phrase (`remove filler words`, `resume render`) and returns names, descriptions and required parameters. Discovery does not check optional backends. |

## Diagnostics and one-call Shorts

| Tool | Description |
|------|-------------|
| `video_doctor` | Read-only JSON verdict covering FFmpeg/FFprobe, Python and optional integrations, workspace permissions and free disk, and the effective guardrail defaults |
| `video_shorts` | One local call for trim → supplied captions → 9:16 template → export; returns one receipt chain and never posts |

**Python client:**
```python
from kinocut import Client
editor = Client()
results = editor.search_tools("subtitle")
# Returns matching tool metadata: {success, query, count, tools}.
```

---

## Visual review evidence

Since 1.16.0, `video_record_motion_acceptance` and CLI `record-motion-acceptance`
join Python `Client.record_motion_acceptance`. Supply the exact `report`,
`input_path`, `reviewer_id`, `source_sha256`, `report_sha256`, complete
`watched_intervals`, flagged-interval `dispositions`, and `verdict` (`accept` or
`reject`). CLI requires either inline `--report-json JSON` or bounded
`--report-file PATH` (UTF-8 JSON, sized for bounded longform producer output).
Watched intervals and dispositions likewise accept mutually exclusive inline
`--watched-intervals-json` / `--dispositions-json` or bounded
`--watched-intervals-file` / `--dispositions-file` inputs. Use files when these
artifacts exceed OS argument limits; file caps derive from producer/evidence
counts while inline JSON keeps its 1 MiB cap. The result nests the content-hashed `receipt`. This is an explicit
caller attestation: `attestation_verified_by_system=false`, not authenticated
proof of viewing or release approval. Agents must never invent the human inputs.

`video_qc_vision` prepares retained keyframes for human visual review. It reports
`sampling_status` separately from `assessment_status`; preparing frames does not
establish visual quality. With no executable VLM scorer, complete sampling returns
`verdict="not_evaluated"` and incomplete sampling returns `"inconclusive"`.
Setting `require_vlm=true` fails closed when assessment is unavailable; it never
grants network permission. `KINOCUT_VISION_MODE=off` is the default, including
when credentials are present. Prefer inspecting the retained frames through the
host's configured vision model. The legacy QC worker requires explicit
`KINOCUT_VISION_MODE=remote`, `KINOCUT_VISION_MODEL` and `ANTHROPIC_API_KEY`, and
no `KINOCUT_VISION_BASE_URL`. It sends sampled frame bytes and a prompt to
Anthropic. Local/custom product endpoints cannot activate this separate cloud
worker. The request runs in an isolated worker with an elapsed
deadline and byte ceilings; malformed or incomplete responses fail closed. This
does not approve the whole film or establish model accuracy. See
[quality evidence](QUALITY_EVIDENCE.md) for waveform, objective visual measurement
and perceptual voice limits.

`image_analyze_product(use_ai=false)` extracts colors locally. Its optional
description adapter also defaults off. `KINOCUT_VISION_MODE=local` permits only
a loopback `KINOCUT_VISION_BASE_URL` with the Anthropic-compatible Messages
protocol; configure `KINOCUT_VISION_MODEL` for that server. Local requests ignore
environment proxies, reject redirects and do not fall back to cloud. `remote`
explicitly permits hosted endpoints. These legacy adapters do not inherit the
host's provider routing. See [vision and network controls](VISION_PRIVACY.md).

Published controls also include `video_convert(two_pass=true,
target_bitrate=KBPS)` for MP4/MOV, `video_fade(crf=...)`, and
`video_add_audio(mix=true, duration_policy="loop_audio")`. Mixed `pad_audio`
remains unsupported. `video_hls_segment` now has CLI `hls-segment`; it writes
local playlists/segments and does not host them. `video_estimate_operation`,
CLI `estimate`, and `Client.estimate_operation` share the local heuristic:
`estimated_cost_units` is dimensionless and `currency` is null.

---

## Cinematic Creation

Plan video generation like a director of photography before rendering. These tools implement a PUSHING CREATION-compatible pre-production workflow: project scaffold, STYLE_/NEG_ blocks, storyboard tables, and prompt expansion.

| Tool | Description |
|------|-------------|
| `video_project_create` | Scaffold `projects/<slug>/style.md`, `storyboard.md`, and `refs/` using cinematic starter templates |
| `style_pack_read` | Parse STYLE_/NEG_ blocks, including one parenthesized heading annotation; malformed or duplicate declared headings fail |
| `storyboard_read` | Parse storyboard rows from `storyboard.md` or a project directory |
| `shot_prompt_render` | Expand camera/lens direction and style blocks into generic positive/negative prompts; `model_dialect_compiled=false`, no provider execution |

---

## Agent Workflow Engine

Plan, validate, render, recover, and prove a multi-step local video job from one JSON
job-spec over a small allowlisted op set (`probe | trim | resize | convert | crop | merge |
add_text | composite_layers | burn_in`). Every op maps 1:1 to a vetted engine function; params are introspected from
the engine signature; media references are symbolic and workspace-confined. Full schema,
`@ref` grammar, variants, resume, and cleanup are in [WORKFLOWS.md](WORKFLOWS.md); receipt
shapes are in [VIDEO_RECEIPT.md](VIDEO_RECEIPT.md).

| Tool | Description |
|------|-------------|
| `video_workflow_validate` | Fail-closed structural gate for a job-spec (op allowlist, `@ref` resolution, backward-reference-only ordering, per-op param introspection, workspace-confined path safety); renders nothing |
| `video_workflow_plan` | Dry-run plan artifact (`receipt_kind: workflow_plan`): ordered op graph, per-source ffprobe + sha256 hashes where the file exists, output intents, variant summary; renders zero media (`save_plan`, `variant`) |
| `video_workflow_render` | Execute allowlisted ops sequentially and emit a `workflow` provenance receipt (per-step input/output hashes, cleanup manifest, determinism caveat); supports `resume_receipt`, `save_receipt`, `keep_intermediates`, `variant`, `all_variants`, `save_receipt_dir` |
| `video_workflow_inspect` | Summarize any receipt this project emits — `workflow`, `workflow_plan`, or `layer_plan` (v2 or legacy v1 without `receipt_kind`) — with a read-only integrity re-check, human-review pointers, and known limitations |

---

## Dedicated Video Rescue

The rescue tools form one review-first local pipeline. Plan and inspect before render; pass
only IDs from the plan's `safe_repairs`; inspect the final receipt before trusting the
package. Full contracts and examples are in [RESCUE.md](RESCUE.md).

| Tool | Description |
|------|-------------|
| `video_rescue_plan` | Analyze one local video without rendering; return evidence, previews, policy-classified safe/recommended/unavailable/blocked work, package intents, and an estimate |
| `video_rescue_render` | Apply approved safe repair IDs from an immutable reviewed plan; fail closed on staleness, dependency drift, cancellation, or verification failure |
| `video_rescue_inspect` | Inspect a plan or receipt and re-check promoted artifact hashes, verification, privacy, resume, and cleanup state without modifying media |

---

## Post-Rescue Planning

These JSON-compatible tools are side-effect-free planners and verifiers. They do not render,
download models, contact providers, or submit jobs. See
[POST_RESCUE_FEATURES.md](POST_RESCUE_FEATURES.md) for operations and guardrails.

| Tool | Description |
|------|-------------|
| `video_semantic_timeline` | Build a source-time semantic timeline from supplied analyzer evidence |
| `video_semantic_query` | Query local source-backed spans without invented descriptions |
| `video_timeline_edit_plan` | Build an EDL, approval binding, visible diff, and verification |
| `video_visual_transform_plan` | Plan analysis, subject-aware reframing, or stabilization |
| `video_restoration_plan` | Plan or evaluate evidence-gated restorative work |
| `video_composition_plan` | Build manifests, selections, compositions, previews, compiled plans, and checks |
| `video_creative_autopilot_plan` | Coordinate declared proven local planners or abstain |
| `video_remote_egress_plan` | Plan explicit remote egress and fake-adapter receipts without network I/O |

---

## Core Editing

| Tool | Description |
|------|-------------|
| `video_info` | Get metadata: duration, resolution, codec, fps, file size |
| `video_info_detailed` | Extended metadata with scene detection and dominant colors |
| `video_trim` | Trim by finite start time + duration or absolute end; `accurate=true` selects frame-accurate seeking; staged output preserves the destination on render/result failure |
| `video_merge` | Concatenate clips with optional per-pair transitions; warns on resolution/FPS/audio mismatches and rejects transitions longer than the shortest clip |
| `video_add_text` | Overlay text with positioning, font, color, shadow |
| `video_add_texts` | Overlay multiple text elements in a single FFmpeg pass; auto-detects overlaps and distributes stacked texts at the same named position |
| `video_add_audio` | Add, replace, or mix audio tracks with fade effects; validates volume and warns on timing/sample-rate risks |
| `video_resize` | Change resolution or apply preset aspect ratios (16:9, 9:16, 1:1, etc.) |
| `video_convert` | Convert between mp4, webm, gif, mov, hevc, av1, prores (two-pass encoding); validate a staged output before publication so failures preserve an existing destination |
| `video_speed` | Speed up or slow down (0.5x = slow-mo, 2x = time-lapse), with staged output publication |
| `video_reverse` | Reverse video and audio playback |
| `video_fade` | Fade in/out over the bounded primary-picture window, preserving delayed origins rather than using longer container/audio duration |
| `video_crop` | Crop in upright display pixels, including rotation-tagged phone video; explicit odd dimensions reject, percentage dimensions become even, pixel offsets stay exact |
| `video_rotate` | Rotate 90/180/270 and flip horizontal/vertical |
| `video_filter` | Apply bounded visual/audio filters; Ken Burns defaults to one frame per input at source fps, noise reduction uses -50 dB by default with explicit `noise_level` override |
| `video_chroma_key` | Remove solid color background (green screen) with bounded similarity/blend parameters |
| `video_stabilize` | Stabilize shaky footage (requires FFmpeg with vidstab) |
| `video_subtitles` | Burn `.srt`/`.vtt`/authored `.ass` subtitles into video; optional `style` force_style override (omit to preserve authored ASS PlayRes/styles/positions). SRT/VTT are rendered dimension-aware via a synthesized ASS whose PlayResX/Y match the probed display size |
| `video_subtitles_styled` | Burn subtitles with custom styling (font, size, color, outline) |
| `video_generate_subtitles` | Create SRT from text entries, optionally burn in |
| `video_watermark` | Add image watermark with validated opacity and positioning |
| `video_overlay` | Picture-in-picture overlay with opacity and timing guardrails |
| `video_composite_layers` | Spec-driven ordered image/video layer compositing with explicit straight/premultiplied input alpha, transforms, timing windows, masks/mattes, full-canvas and allowlisted positioned blend modes, rotation/pivot, named layer/mask/mask-edge `effect-noise` routes, dry-run plans, and deterministic `layer_plan` v2 receipts (video-only output) |
| `video_split_screen` | Side-by-side or top/bottom layout with duration/FPS/audio mismatch warnings |
| `video_edit` | Full timeline-based edit from JSON DSL, or sequence shortcut (`clips` + optional `transitions` / `transition_duration`) |
| `video_create_from_images` | Create a frame-exact video from an image sequence: one output frame per input, numeric or rational `fps` (greater than 0, at most 60), and optional `list_file` input (one path per line). At most 18,000 images; a list file may be at most 18,432,000 bytes |
| `video_export_frames` | Export video as individual image frames |
| `video_extract_frame` | Extract a frame; omitted `timestamp` uses smart sampling when available, otherwise 10% of duration; explicit `timestamp=0` means the first frame, matching CLI/Python |
| `video_extract_audio` | Extract audio as mp3, wav, aac, ogg, or flac |
| `video_export` | Render with quality and format settings; optional C2PA signing for final MP4 exports via `c2pa_manifest_path` |
| `video_normalize_audio` | Normalize audio/video loudness; `target_lufs`, `lra`, `true_peak_dbtp`, `fade_seconds` set delivery controls. WAV uses PCM16, supported M4A/video uses AAC with staged codec/full-decode validation |
| `video_batch` | Apply the same operation to multiple video files |
| `video_cleanup` | Remove Kinocut-managed intermediate files |
| `video_hls_segment` | Segment video into HLS format with multi-quality variants |
| `video_template_preview` | Preview social/video template operations before rendering |
| `video_validate_text_layout` | Validate text overlays for overlap, low contrast, unsafe positioning, and missing shadows before rendering |

Non-`normal` blends support opacity and `start`/`duration` windows in two geometries: full-canvas at `{0,0}` without explicit sizing, or a positioned rectangle with both positive integer `width` and `height` and an integral nonnegative in-canvas position. RGB blending avoids applying color arithmetic to subsampled chroma planes. Scale, rotation/pivot, mask/matte, fractional positions and out-of-canvas rectangles remain deferred and fail closed with `unsupported_blend_geometry`. Video layers and video masks start playing from their declared layer `start`; a timing window does not merely hide footage already playing from the canvas origin. File sources and masks must resolve inside the spec directory; place the spec in a common parent of its media.
Layer `alpha_mode` is `straight` by default; `premultiplied` image/video inputs are explicitly unpremultiplied before transforms and compositing. Top-level `passes` route `effect-noise` through `layer:<id>`, `layer:<id>.mask`, or `layer:<id>.mask.edge`. Unknown targets, effects, route/argument fields, and mask routes without a mask fail closed with stable validation errors.

---

## AI-Powered

| Tool | Description | Dependencies |
|------|-------------|--------------|
| `video_analyze` | Comprehensive video analysis: transcript, metadata, scenes, audio, quality, chapters, and colors | FFmpeg; optional Whisper/image extras |
| `video_ai_remove_silence` | Auto-remove silent sections with configurable threshold | FFmpeg |
| `video_ai_transcribe` | Speech-to-text with timestamp alignment | [openai-whisper](https://pypi.org/project/openai-whisper/) |
| `video_intent` | Route ~10 semantic intent verbs to a plan (no silent media mutation). Optional `goal=` compiles a reviewable cutfile. A 360/desk/table/`x4` `goal` plus `source=` also attaches a `360_assembly_plan` (`next_action: review_then_sphere_render`). See [360_ASSEMBLY.md](360_ASSEMBLY.md). | — |
| `video_propose_broll` | Transcript-keyed b-roll proposals; **human review required**, never silent insert | — |
| `video_translate_captions` | Translate SRT with honest coverage (EN→ES offline map first) | — |
| `video_language_coverage` | Honest per-surface matrix for transcribe / translate / dub | — |
| `video_review_run` | Watching guardrail: offline metric floor under a review policy | FFmpeg |
| `video_review_decide` | Human accept/reject/revise on a `review_run` artifact. If `review_run.artifact_kind` is `360_assembly_plan`, `approve`/`accept`/`reject` that plan and optionally render when `output_path` is set. | — |
| `video_ai_scene_detect` | ML-enhanced scene change detection (perceptual hashing) | [imagehash](https://pypi.org/project/imagehash/), Pillow |
| `video_ai_stem_separation` | Isolate vocals, drums, bass, other instruments | [demucs](https://pypi.org/project/demucs/), Torch, TorchAudio, TorchCodec |
| `video_ai_upscale` | AI super-resolution upscaling (2x or 4x) | [opencv-contrib-python](https://pypi.org/project/opencv-contrib-python/); Real-ESRGAN/BasicSR where supported |
| `video_ai_color_grade` | Color grading with style presets, reference matching or an explicit `lut_path` | FFmpeg |
| `video_quality_check` | Check brightness, contrast, saturation, audio levels, color balance |
| `video_design_quality_check` | Full design quality analysis: layout, typography, color, motion, composition |
| `video_fix_design_issues` | Auto-fix brightness and saturation issues (audio is not changed; use `video_normalize_audio`) |
| `video_release_checkpoint` | Hard quality gate plus thumbnail/storyboard artifacts before publishing |

Install only the AI dependencies you need:

```bash
pip install "kinocut[transcribe]==2.0.1"  # Whisper transcription
pip install "kinocut[ai-scene]==2.0.1"    # perceptual scene hashing
pip install "kinocut[stems]==2.0.1"       # Demucs stem separation
pip install "kinocut[upscale]==2.0.1"     # OpenCV upscaling; Real-ESRGAN/BasicSR where supported
pip install "kinocut[ai]==2.0.1"          # all AI extras, kept for compatibility
pip install yt-dlp                   # only for downloading platform URLs (YouTube/Vimeo/...)
```

AI upscaling checks both estimated and actual extracted frame counts before
model initialization, stages final output, and rejects input/output aliases.
Failed frame writes and source-audio extraction abort instead of publishing
shortened or silent media.
The default test suite verifies these admission and publication controls with
native media and simulated inference. It does not establish model execution or
equivalent quality between OpenCV and Real-ESRGAN. BasicSR 1.4.2 retains an
unpatched advisory in its unused distributed initializer and a legacy import
incompatibility with modern TorchVision; consult [fleet upgrade guidance](FLEET_UPGRADE.md)
before enabling optional backends.

---

## Hyperframes — HTML-Native Video

Telemetry defaults off. Browser previews require verified Hyperframes 0.8.104 or
0.8.140; Docker renders and previews on other versions require explicit
`KINOCUT_HYPERFRAMES_TELEMETRY=true`. This consent does not enable provider
captions or image analysis. See [vision and network controls](VISION_PRIVACY.md).

Relative render and requested still output paths resolve from the caller working
directory. A requested still output is atomically copied independently of mutable
snapshots and contains PNG bytes; changing its extension does not transcode it.
Without an explicit output, the existing snapshot path may be replaced by a later
snapshot. Missing still artifacts are errors.


Create videos programmatically using [Hyperframes](https://hyperframes.io/) — an HTML-native framework for video (Apache 2.0). Hyperframes owns HTML-video authoring, catalog blocks, website capture, local TTS, transcription import, background removal, layout inspection, diagnostics, benchmarking, and rendering; Kinocut wraps those operations for MCP-safe orchestration and FFmpeg post-processing.

| Tool | Description |
|------|-------------|
| `hyperframes_init` | Scaffold a new Hyperframes project (blank, warm-grain, swiss-grid templates; optional media bootstrap, Tailwind, and resolution preset flags) |
| `hyperframes_render` | Render a Hyperframes composition to video (MP4/WebM/MOV/PNG sequence; optional composition, resolution preset, and runtime `variables` / `variables_file` flags; arbitrary width/height pairs are rejected instead of silently ignored) |
| `hyperframes_snapshot` | Capture actual PNG snapshot paths written by Hyperframes with optional runtime `variables` / `variables_file` data |
| `hyperframes_still` | Backward-compatible single-frame snapshot helper with optional runtime `variables` / `variables_file` data |
| `hyperframes_inspect` | Inspect rendered layout for overflow and visual issues |
| `hyperframes_info` | Read project metadata |
| `hyperframes_catalog` | Browse catalog blocks/components, including social overlays and caption styles |
| `hyperframes_capture` | Capture a website as editable Hyperframes components |
| `hyperframes_tts` | Generate speech audio with local Hyperframes TTS or list available voices |
| `hyperframes_transcribe` | Transcribe media to word-level timestamps or import transcripts |
| `hyperframes_remove_background` | Cut a person (default `u2net_human_seg`) or a product/object (`model="birefnet-general"`, `kinocut[object-matte]==2.0.1`) out of a still or video. `info=true` lists models without downloading. No new tool name. Guide: [PRODUCT_MATTE.md](PRODUCT_MATTE.md) |
| `hyperframes_doctor` | Run Hyperframes environment diagnostics |
| `hyperframes_benchmark` | Compare render speed and output size, with configurable run count |
| `hyperframes_compositions` | List all compositions in a project |
| `hyperframes_preview` | Launch Hyperframes preview studio |
| `hyperframes_validate` | Check project structure and run lint |
| `hyperframes_add_block` | Install a block from the Hyperframes catalog, with optional clipboard suppression |
| `hyperframes_to_mcpvideo` | Pipeline: render with Hyperframes, then post-process with Kinocut |

---

## Revideo — guarded local code video

| Tool | Purpose |
| --- | --- |
| `revideo_materialize` | Copy Kinocut's pinned bridge template and write a validated job. |
| `revideo_install` | Run bounded `npm ci` against the committed lockfile. |
| `revideo_render` | Render a verified materialized project and atomically publish its output. |
| `revideo_render_job` | Run materialize, install, render, decode verification, and receipt generation. |

`npm ci` can access the npm registry; rendering then runs on the local machine.
A supplied `scene_source` is trusted executable TypeScript. Kinocut rejects altered
control files, symlinks below the project root, malformed jobs, invalid timeouts,
and unverified output. Each render uses a fresh private project output, verifies
counted frames plus a full decode, and updates prior project and final outputs
only after validation. Render responses include output and exact on-disk job-file
SHA-256 digests, observed dimensions, fps, frame count, duration, render time,
and project directory. `.mp4`, `.webm`, and `.mov` select pinned MP4, WebM,
and ProRes 4444 exporter modes, with encoded format checks before publication. Run a
quality check and human visual review before publication. Local concurrent path
replacement, process crashes, and trusted scene behavior remain outside this
bounded in-process rollback guard. The job file is capped at one MiB; its
pre/post render binding is byte-exact, so formatting-only mutation also rejects
publication.

## Repurposing

Create local YouTube/social media packages from one source video. Publishing and scheduling are intentionally out of scope for v1; the tools produce files, manifests, thumbnails, storyboards, and optional release-checkpoint artifacts for a human or downstream publisher to review.

| Tool | Description |
|------|-------------|
| `video_repurpose_plan` | Dry-run a platform manifest with vertical, horizontal, and square output variants |
| `video_repurpose` | Render platform-ready assets plus thumbnails, storyboards, release-checkpoint artifacts, and `repurpose_manifest.json` |

---

## Stream shorts (saved-plan stages)

Local-only review → render → package over a persisted shorts plan. No posting.
See [STREAM_SHORTS.md](STREAM_SHORTS.md).

| Tool | Description |
|------|-------------|
| `shorts_plan_show` | Load a saved plan and return source-free proposals for review |
| `shorts_review` | Append one human decision (`approve` / `reject` / trim / title / sensitivity) |
| `shorts_render` | Render platform drafts for an approved candidate; cache unchanged digests |
| `shorts_package` | Write portable packages (video, SRT, thumbnail, metadata, manifest) |

---

## Sound public operations

Bounded local-first sound discovery and invoke via `kinocut_sound.public`. This is **not** full-episode sonic-world completion. Results are JSON-safe and fail closed on hostile/privacy boundaries.

| Tool | Description |
|------|-------------|
| `sound_capabilities` | Discover the bounded public sound operation set (local-first, non-TTY JSON) |
| `sound_plan_validate` | Validate a supplied SoundPlan, including typed state; explicit invalid plans fail. Omission retains the minimal example. See [input validation](SOUND_INPUT_VALIDATION.md). |
| `sound_voice_batch` | Retain local EN/ES caption speech with `request` + `project_root`, including V2 [dry/distance profiles](SOUND_SPEECH_SPATIAL.md); legacy `plan` mode is a labelled synthetic demo. See [caption speech](SOUND_DUB_REQUESTS.md). |
| `sound_mix_render` | Assemble supplied WAVs with [routing](SOUND_ROUTING_REQUESTS.md), [automation](SOUND_AUTOMATION_REQUESTS.md), [sends](SOUND_SEND_REQUESTS.md), [final sidechains](SOUND_SIDECHAIN_REQUESTS.md), [layers/loop fill/ducking](SOUND_LAYER_REQUESTS.md) and V4 [source-rate conversion](SOUND_RATE_CONVERSION.md). Takes a persisted request and project root. No-argument labelled demo remains available. See [request contract](SOUND_MIX_REQUESTS.md). |
| `sound_qa_loudness` | Measure the first audio stream of hashed supported local audio/video containers with FFmpeg and report actual policy compliance; omit inputs for a labelled demo. See [meter request](SOUND_LOUDNESS_REQUESTS.md). |
| `sound_master_render` | Retain a mono/stereo two-pass master ZIP only after measuring final audio against its policy. Requires `request` and `project_root`; see [master request](SOUND_MASTER_REQUESTS.md). |
| `sound_qa_asr` | Recognize hashed local audio and retain reference comparison. Requires `request` and `project_root` ([contract](SOUND_ASR_REQUESTS.md)) |

---

<a id="audio-synthesis-9-tools"></a>

## Audio Synthesis

Plain-file `Client.mix_audio` and `Client.duck_audio` also have published CLI
adapters `mix-audio` and `duck-audio`. The published 1.16.0 MCP addition is
`video_mix_audio`; `video_duck_audio` already existed. See
[audio mixing](AUDIO_MIXING.md) for engine behavior.

Generate audio from code — no external audio files needed. Pure NumPy, no extra dependencies.

| Tool | Description |
|------|-------------|
| `audio_synthesize` | Generate waveforms: sine, square, sawtooth, triangle, noise. With envelopes, reverb, filtering. |
| `audio_preset` | 15 pre-configured sounds: UI blips, ambient drones, notification chimes, data sounds |
| `audio_sequence` | Compose timed audio events into a layered track |
| `audio_compose` | Mix multiple WAV tracks with individual volume control |
| `audio_effects` | Apply effects chain: lowpass, reverb, normalize, fade |
| `video_add_generated_audio` | Generate audio and add it to a video in one call |
| `video_audio_spatial` | 3D spatial audio positioning (azimuth + elevation) |
| `video_mix_audio` | Mix `sounds` (track array or JSON array with `path`, `start`, `volume`, `fade_in`, `fade_out`) using one AAC encode and picture stream copy; `keep_source` and `audio_bitrate` controls. Gains sum and may clip; no automatic loudness normalization or governed audio-bed receipt |
| `video_duck_audio` | Mix background music under a video's voice with automatic sidechain ducking; music dips while speech plays and recovers in pauses |
| `video_audio_bed` | Governed one-shot audio-bed: duck a music bed under a voice track, normalize to EBU R128 `target_lufs`, optionally loop with crossfade, and emit a deterministic edit-receipt (`AudioBedReceipt`, `operation: "audio_bed"`, fixed `keep_video` duration policy). The receipt lands at top-level `result["receipt"]`; no authorization, duration-policy, or duration-tolerance parameter is exposed. |

---

## Visual Effects

| Tool | Description |
|------|-------------|
| `effect_vignette` | Darken edges for cinematic focus |
| `effect_chromatic_aberration` | RGB color separation (glitch aesthetic) |
| `effect_scanlines` | Retro CRT scanline effect with flicker |
| `effect_noise` | Film grain and digital noise |
| `effect_glow` | Bloom/glow for highlights |
| `video_apply_mask` | Apply image mask with edge feathering |
| `video_luma_key` | Mask out dark regions based on luminance (brightness) |
| `video_shape_mask` | Circle, rounded_rect or oval mask; default MOV retains alpha, explicit MP4 composites over black; static masks loop for video duration |

---

## Transitions

| Tool | Description |
|------|-------------|
| `transition_glitch` | RGB shift + noise for digital distortion |
| `transition_pixelate` | Block dissolve with configurable pixel size |
| `transition_morph` | Mesh warp transition |

---

## Glitch Effects

CPU-based glitch effects run entirely through FFmpeg. GPU-accelerated effects (marked below) require Node.js, the `MCP_VIDEO_CRUSH_PATH` environment variable pointing to the [CRUSH](https://github.com/pushingsquares/crush) shader sources, and the `canvas` npm package — install it once with `npm install` inside `kinocut/_crush_shader/`. The tools report exactly which piece is missing.

| Tool | Description |
|------|-------------|
| `glitch_rgb_shift` | Shift red and blue channels in opposite directions for a chromatic split look; optional per-frame noise for jitter |
| `glitch_scanline_jitter` | Displace random horizontal rows of pixels for a CRT malfunction look |
| `glitch_screen_tearing` | Create horizontal tear bands at varying Y positions that shift left/right over time |
| `glitch_vhs_tracking` | Simulate VHS tape tracking errors with color bleed, rolling bands, and analog noise |
| `glitch_macroblocking` | Simulate codec artifacting with downscale/upscale pixelation and color posterization |
| `glitch_datamoshing` | Simulate P-frame corruption where displacement drifts across frames then periodically resets |
| `glitch_cmyk_split` | Shift RGB channels at 90-degree intervals to simulate four-plate offset print registration errors |
| `glitch_turbulent_displacement` | Layered sin/cos noise approximating fractal Brownian motion for organic-looking displacement |
| `glitch_digital_feedback` | Iterative frame feedback with scale/rotation transform, creating ghostly trails and recursive patterns (requires Node.js + GPU) |
| `glitch_slit_scan` | Sample each row/column from a different past frame for a time-smeared slit-scan effect (requires Node.js + GPU) |
| `glitch_depth_splatting` | Extract pseudo-depth from luminance and render the image as scattered points in 3D (requires Node.js + GPU) |
| `glitch_point_cloud` | Sample the image as scattered points in a 3D-rotated grid with depth-based displacement (requires Node.js + GPU) |

---

## Layout & Motion Graphics

| Tool | Description |
|------|-------------|
| `video_layout_grid` | Grid layout for multiple videos (2x2, 3x1, etc.) with clip-count and duration mismatch warnings |
| `video_layout_pip` | Picture-in-picture with border and positioning |
| `video_text_animated` | Animated text overlays (fade, slide, typewriter) with color, timing, and overflow guardrails |
| `video_mograph_count` | Animated number counter video |
| `video_mograph_progress` | Progress bar/circle/dots animation |
| `video_auto_chapters` | Auto-detect scenes and create chapter timestamps |

---

## Analysis

| Tool | Description |
|------|-------------|
| `video_detect_scenes` | Auto-detect scene changes with threshold control |
| `video_thumbnail` | Extract a single frame (thumbnail / frame grab) at any timestamp |
| `video_preview` | Generate fast low-res preview |
| `video_storyboard` | Extract key frames as a grid for review |
| `video_review_card` | Write a self-contained HTML review card (contact sheet, facts, Approve / Dig in / Try another range buttons) for Hermes Desktop chat |
| `video_compare_quality` | Compare PSNR/SSIM quality metrics between videos |
| `video_read_metadata` | Read video metadata tags |
| `video_write_metadata` | Write video metadata tags |
| `video_audio_waveform` | Measure first-stream RMS dBFS bins and silence regions; distinguish real measurements from `synthetic=true` fallback. [Evidence contract](QUALITY_EVIDENCE.md#audio-waveform) |

---

## Image Analysis

| Tool | Description |
|------|-------------|
| `image_extract_colors` | Extract dominant colors from an image or video frame via K-means clustering (1-20 colors) |
| `image_generate_palette` | Generate color harmony palette from an image or video frame |
| `image_analyze_product` | Extract colors locally; optional legacy provider description requires explicit vision mode consent |

## Still / plate editor

See [STILL_PLATES.md](STILL_PLATES.md) for order-of-ops, signal LUTs, and cohesion gate policy.

| Tool | Description |
|------|-------------|
| `still_match` | Match a package of stills to a hero with one shared WB/exposure gain; receipt + no source overwrite |
| `still_grade` | Ordered grade correct→match→look; optional 3D LUT last; signal-mode near-extrema logging |
| `still_gate` | Fail-closed cohesion gate (luma spread, shadow green/cyan) + contact sheet |
| `image_edit` | Free establish-locked still edit with plan/receipt; paid gen off by default |
| `still_package` | Full package job: edit beats → match → grade → gate |

## Complete index

Every entry below is generated from the code, so nothing is missing. The sections above explain the important ones in depth.

<!-- BEGIN GENERATED INDEX -->
<!-- Generated by scripts/generate_reference_index.py; edit the code, then rerun it. -->

206 tools with `KINOCUT_TOOLS=all`, grouped by the family that dispatches them on the default surface.

### `video_edit_ops`: Edit operations (trim, merge, text, convert, export, metadata, batch) (44)

| Tool | Summary |
| --- | --- |
| `video_add_audio` | Add, replace, or mix an audio track into a video and render a new file; the sources are only read. Returns JSON {success, output_path}. |
| `video_add_text` | Burn one text element (title, caption, watermark) into a video. Returns JSON {success, output_path}. |
| `video_add_texts` | Overlay multiple text elements on a video in a single FFmpeg pass. |
| `video_apply_mask` | Apply an image mask to a video with edge feathering. |
| `video_audio_waveform` | Extract audio waveform data (peaks and silence regions). |
| `video_batch` | Apply the same operation to multiple video files. |
| `video_chroma_key` | Remove a solid color background (green screen / chroma key). |
| `video_cleanup` | Delete intermediate video files after a workflow. |
| `video_compare_quality` | Compare video quality between original and processed versions. |
| `video_composite_layers` | Composite ordered image/video layers from a JSON spec. |
| `video_convert` | Transcode a video into a different container or codec (mp4, webm, gif, mov, ...). Returns JSON {success, output_path}. Use for format conversion; prefer video_export for delivery presets. Pass input_path as the source video and format as the target container; long renders stream MCP progress. |
| `video_create_from_images` | Create a frame-exact video from a sequence of images. |
| `video_crop` | Crop an existing video to a rectangular region or centered percentage crop and render a new output file. The source video is read only; x/y default to a centered crop when omitted. |
| `video_detect_scenes` | Detect scene changes in a video. |
| `video_edit` | Execute a full timeline-based edit from a JSON specification. |
| `video_export` | Re-encode an existing video for final delivery using a quality preset and output format. Use this for publishing-ready renders; use video_convert when the main goal is container/codec conversion. The source video is read only and a new output file is produced. |
| `video_export_frames` | Export frames from a video as individual images. |
| `video_extract_audio` | Extract the audio track from a video file. |
| `video_fade` | Render fade-in and/or fade-out effects onto an existing video without modifying the source file. Use fade_in for a fade from black at the start and fade_out for a fade to black at the end; output_path is created or overwritten. |
| `video_filter` | Apply a visual filter to a video. |
| `video_generate_subtitles` | Generate SRT subtitles from text entries and optionally burn into video. |
| `video_hls_segment` | Segment a video into HLS (HTTP Live Streaming) format. |
| `video_info` | Probe a video file for metadata. Returns JSON {success, info:{duration, resolution, codec, fps, size, ...}}. Use before any edit to learn the source's dimensions and length. |
| `video_luma_key` | Mask out dark regions based on luminance (brightness). |
| `video_merge` | Concatenate two or more video clips, in order, into one rendered file. Returns JSON {success, output_path}. |
| `video_normalize_audio` | Normalize audio loudness to a target LUFS level. |
| `video_overlay` | Picture-in-picture: overlay a video on top of another. |
| `video_preview` | Generate a fast low-resolution preview for quick review. |
| `video_read_metadata` | Read metadata tags from a video/audio file. |
| `video_resize` | Resize a video or change its aspect ratio. Returns JSON {success, output_path}. Use to fit a video to target dimensions or a preset ratio. Pass input_path as the source video (e.g. from video_info) and either width/height or aspect_ratio to define the target. |
| `video_reverse` | Reverse video and audio playback so it plays backwards. |
| `video_review_card` | Write an HTML review card (contact sheet, facts, action buttons) for Hermes Desktop chat. |
| `video_rotate` | Rotate and/or flip an existing video and render a new output file. Supports right-angle rotations plus horizontal and vertical flips; the input video is not modified. |
| `video_shape_mask` | Apply a geometric shape mask to a video. |
| `video_speed` | Render a new video with playback speed changed; the source video is left unchanged. Returns JSON {success, output_path}. Use for slow-motion or fast-forward effects. Pass input_path as the source video and factor as the multiplier (below 1.0 slows, above 1.0 speeds up). |
| `video_split_screen` | Place two videos side by side or top/bottom. |
| `video_stabilize` | Stabilize a shaky video using motion vector analysis. |
| `video_storyboard` | Extract key frames and create a storyboard grid for human review. |
| `video_subtitles` | Burn subtitles (SRT/VTT/authored ASS) into a video. |
| `video_template_preview` | Preview what a video template would do before rendering. |
| `video_thumbnail` | Extract a single frame (thumbnail / frame grab) from a video. |
| `video_trim` | Cut a segment out of a video by start time and duration or end. Returns JSON {success, output_path} pointing at the rendered clip. |
| `video_watermark` | Overlay an image watermark onto an existing video and render a new output file. The video and watermark image are read only; output_path is created or overwritten. Supports named, pixel, and percentage positions plus opacity, margin, CRF, and preset controls. |
| `video_write_metadata` | Write metadata tags to a video/audio file. |

### `video_effects_ops`: Effect operations (filters, transitions, glitch, motion graphics) (28)

| Tool | Summary |
| --- | --- |
| `effect_chromatic_aberration` | Apply chromatic aberration - RGB channel separation. |
| `effect_glow` | Apply bloom/glow effect for highlights. |
| `effect_noise` | Apply film grain or digital noise. |
| `effect_scanlines` | Apply CRT-style scanlines overlay. |
| `effect_vignette` | Apply vignette effect - darkened edges. |
| `glitch_cmyk_split` | Apply CMYK split glitch effect. |
| `glitch_datamoshing` | Apply datamoshing glitch effect. |
| `glitch_depth_splatting` | Apply depth-based point splatting effect (requires Node.js + GPU). |
| `glitch_digital_feedback` | Apply digital feedback glitch effect (requires Node.js + GPU). |
| `glitch_macroblocking` | Apply macroblocking glitch effect. |
| `glitch_point_cloud` | Apply point cloud rendering effect (requires Node.js + GPU). |
| `glitch_rgb_shift` | Apply RGB channel shift glitch effect. |
| `glitch_scanline_jitter` | Apply scanline jitter glitch effect. |
| `glitch_screen_tearing` | Apply screen tearing glitch effect. |
| `glitch_slit_scan` | Apply slit-scan temporal displacement effect (requires Node.js + GPU). |
| `glitch_turbulent_displacement` | Apply turbulent displacement glitch effect. |
| `glitch_vhs_tracking` | Apply VHS tracking error glitch effect. |
| `transition_glitch` | Apply glitch transition between two video clips. |
| `transition_morph` | Apply morph transition between two video clips. |
| `transition_pixelate` | Apply pixelate transition between two video clips. |
| `video_auto_chapters` | Auto-detect scene changes and create chapters. |
| `video_info_detailed` | Get extended video metadata. |
| `video_layout_grid` | Create grid-based multi-video layout. |
| `video_layout_pip` | Picture-in-picture overlay. |
| `video_mograph_count` | Generate animated number counter video. |
| `video_mograph_progress` | Generate progress bar / loading animation. |
| `video_subtitles_styled` | Burn subtitles from SRT/VTT with custom styling. |
| `video_text_animated` | Add animated text to video. |

### `audio_ops`: Audio operations (mix, synthesize, presets, sound pipeline, QC) (17)

| Tool | Summary |
| --- | --- |
| `audio_compose` | Layer multiple audio tracks with volume mixing. |
| `audio_effects` | Apply audio effects chain to a WAV file. |
| `audio_preset` | Generate preset sound design elements. |
| `audio_sequence` | Compose multiple audio events into a timed sequence. |
| `audio_synthesize` | Generate audio procedurally using synthesis. |
| `sound_capabilities` | Discover the bounded public sound operation set (local-first, JSON-safe). |
| `sound_master_render` | Retain a two-pass master only after measuring final audio against its policy. |
| `sound_mix_render` | Assemble supplied WAVs into a new ZIP; omit both arguments for a labelled demo. |
| `sound_plan_validate` | Validate a SoundPlan payload (or a built-in minimal plan when omitted). |
| `sound_qa_asr` | Recognize supplied local audio and compare it with a reference script. |
| `sound_qa_loudness` | Measure hashed local audio against its policy; omit inputs for a labelled demo. |
| `sound_voice_batch` | Retain local caption speech from a request, or run the synthetic plan demo. |
| `video_add_generated_audio` | Add procedurally generated audio to a video. |
| `video_audio_bed` | Mix a looped music bed under a voice source with ducking and loudness normalization. |
| `video_audio_spatial` | Apply 3D spatial audio positioning. |
| `video_duck_audio` | Mix background music under a video's voice with automatic ducking. |
| `video_mix_audio` | Mix timed sounds with one AAC encode and stream-copy the primary picture. |

### `video_ai_ops`: AI operations (transcription, scene detect, upscale, verdicts, quality) (15)

| Tool | Summary |
| --- | --- |
| `video_acceptance_eval` | Evaluate exact-spec verdict and defect evidence without approving anything. |
| `video_ai_color_grade` | Apply a color grade to a video — by LUT file, style preset, or reference video. |
| `video_ai_remove_silence` | Remove silent sections from video. |
| `video_ai_scene_detect` | Detect scene changes in video. |
| `video_ai_stem_separation` | Separate audio into stems using Demucs. |
| `video_ai_transcribe` | Transcribe speech to text using Whisper. |
| `video_ai_upscale` | Upscale video using AI super-resolution. |
| `video_analyze` | Comprehensive video analysis — transcript, metadata, scenes, audio, quality, chapters, colors. |
| `video_body_swap` | Replace video while preserving approved audio with explicit duration policy. |
| `video_design_quality_check` | Run comprehensive design quality analysis on a video. |
| `video_fix_design_issues` | Auto-fix brightness and saturation in a video; audio is not changed. |
| `video_quality_check` | Run visual quality checks on a video. |
| `video_release_checkpoint` | Create preview artifacts only after the video passes quality gates. |
| `video_salvage` | Create one lineage-bound salvage derivative and a fresh review slot. |
| `video_verdict` | Persist exact-asset analysis; approvals require active human evidence. |

### `image_ops`: Image and still operations (colors, palettes, grade, gate, packaging) (8)

| Tool | Summary |
| --- | --- |
| `image_analyze_product` | Analyze a product image or video frame — extract colors and optionally generate AI description. |
| `image_edit` | Establish-locked still match with plan/receipt (intent is audit metadata). |
| `image_extract_colors` | Extract dominant colors from an image or video frame. |
| `image_generate_palette` | Generate a color harmony palette from an image or video frame. |
| `still_gate` | Fail-closed cohesion gate for a still package + contact sheet. |
| `still_grade` | Grade stills in order correct→match→look; optional 3D LUT applied last. |
| `still_match` | Match a package of stills to a hero plate with one shared WB/exposure gain. |
| `still_package` | Multi-still package workflow: edit beats → match → grade → cohesion gate. |

### `video_qc_ops`: Inspection and release operations (doctor, preflight, guardrails, review, publish) (15)

| Tool | Summary |
| --- | --- |
| `video_benchmark_run` | Run the AI-video benchmark corpus against host capabilities. |
| `video_capabilities` | Probe host capabilities (ffmpeg, whisper, c2pa) and return a capability report. |
| `video_cost_ledger` | Sum known USD cost events by category for the project. |
| `video_doctor` | Return a read-only JSON readiness verdict for the next video job. |
| `video_extract_frame` | Extract one frame as an image. Without a timestamp, picks a smart thumbnail |
| `video_ingest` | Ingest immutable source bytes into an existing or new private project. |
| `video_inspect_temporal` | Build and persist the complete deterministic temporal evidence package. |
| `video_learning_report` | Project a learning report (verdicts, defects, costs, recipes) from records. |
| `video_preflight` | Run unified technical, loudness, color, and decode preflight. |
| `video_publish_gate` | Evaluate the fail-closed publish gate; any blocking finding blocks publishing. |
| `video_recipe_capture` | Capture a workflow recipe (writer); idempotent by canonical digest. |
| `video_record_motion_acceptance` | Record an authorized human caller's explicit whole-film motion attestation. |
| `video_review_decision` | Record a human review decision (writer); corrections supersede by record id. |
| `video_review_package` | Assemble a review package and publish-gate verdict for a candidate artifact. |
| `video_validate_text_layout` | Validate a set of text overlays for visual failure modes before rendering. |

### `video_plan_ops`: Planning operations (intent, cutfiles, timelines, rescue, workflow, repurpose) (51)

| Tool | Summary |
| --- | --- |
| `shot_prompt_render` | Expand one storyboard shot into prompt and negative_prompt strings. |
| `storyboard_read` | Read a PUSHING CREATION storyboard table from storyboard.md or a project directory. |
| `style_pack_read` | Read STYLE_ and NEG_ blocks from a style.md file or project directory. |
| `video_audiogram_plan` | Audiogram + chapter mark plan (TE.4). |
| `video_brand_kit` | Save or load a brand kit / style profile JSON. |
| `video_composition_plan` | Build source-backed manifests, selections, compositions, previews, and checks. |
| `video_creative_autopilot_plan` | Coordinate proven local planners or return a structured abstention. |
| `video_cutfile_render` | Render a schema-valid Cutfile via the workflow engine (Track E). |
| `video_cutfile_validate` | Validate a Cutfile, or compile one from ``goal`` / ``platform`` (N1/N5). |
| `video_dub_plan` | ES-first plan; use sound_voice_batch with a hashed request for local stock speech. |
| `video_edit_session` | Conversational edit session. Step with ``input_path`` measures real QC (N6). |
| `video_estimate_operation` | Dry-run local wall-time / cost-unit estimate (not cloud pricing). |
| `video_find_moments` | Persist or query a revision-bound local semantic index. |
| `video_generative_plan` | Generative policy and spend-cap planning metadata (P4.1). |
| `video_hook_candidates` | Thumbnail + hook-title candidates for human pick (TE.2). |
| `video_init_project` | Scaffold a local Kinocut project directory (media/out/receipts + optional Cutfile). |
| `video_intent` | Route a semantic intent verb to a plan (does not silently mutate media). |
| `video_language_coverage` | Honest per-surface language coverage for transcribe/translate/dub. |
| `video_metric_qc` | Offline metric floor (duration/black/loudness) — fail-closed, no invented values. |
| `video_otio_export` | Export Timeline IR to simplified OTIO JSON (P4.2). |
| `video_otio_import` | Import simplified OTIO JSON to Timeline IR (P4.2). |
| `video_project_create` | Scaffold a cinematic video project with style, storyboard, and refs folders. |
| `video_project_recipe_export` | Export a verified edit revision as a path-free portable recipe. |
| `video_project_recipe_replay` | Replay a portable recipe into a new durable project revision. |
| `video_propose_broll` | Transcript-keyed b-roll proposals — human review required, never silent insert. |
| `video_propose_mutations` | Map QC findings to typed proposed mutations (human apply only). |
| `video_publish_validate` | Validate a publish spec. ``solve=True`` also emits a cutfile (N5). |
| `video_punch_zoom_plan` | Auto-zoom punch-in plan on cut points (TE.5). |
| `video_qc_narrative` | Narrative/retention heuristics incl. first-15s window (P3.4). |
| `video_qc_vision` | Prepare keyframes for visual review; provider assessment is disabled by default. |
| `video_remote_egress_plan` | Plan explicit remote egress and fake adapter receipts without network I/O. |
| `video_repurpose` | Submit one durable projectstore repurpose job for platform clips. |
| `video_repurpose_plan` | Create a dry-run local repurposing manifest for platform-ready assets. |
| `video_rescue_inspect` | Inspect a rescue plan or receipt and re-check artifact integrity. |
| `video_rescue_plan` | Analyze one local video and return a policy-classified rescue plan. |
| `video_rescue_render` | Render approved safe repairs from a reviewed rescue plan. |
| `video_restoration_plan` | Plan or evaluate evidence-gated local restorative work. |
| `video_review_decide` | Record human accept/reject/revise. Accept + EDL approval can render (N4). |
| `video_review_run` | Watching guardrail: run offline metric floor under a review policy. |
| `video_review_ui` | Write hot-reloading human review HTML surface (P4.3). |
| `video_seek_frame` | Frame-accurate seek conversion (TE.9). |
| `video_semantic_query` | Query source-backed semantic spans locally without inventing descriptions. |
| `video_semantic_timeline` | Build a local, source-time semantic timeline from supplied analyzer evidence. |
| `video_timeline_edit_plan` | Plan explicit or ordinary-person timeline edits as a reviewable EDL and diff. |
| `video_timeline_ir_validate` | Validate Timeline IR and compile to render DAG (P3.0). |
| `video_translate_captions` | Translate SRT captions with honest language-coverage reporting (EN→ES first). |
| `video_visual_transform_plan` | Plan subject/camera analysis, reframing, or stabilization with crop budgets. |
| `video_workflow_inspect` | Summarize any receipt this project emits, with a read-only integrity check. |
| `video_workflow_plan` | Produce a no-render plan for an agent workflow job-spec. |
| `video_workflow_render` | Execute an agent workflow job-spec and return a provenance receipt. |
| `video_workflow_validate` | Validate an agent workflow job-spec without rendering any media. |

### `platform_ops`: Platform operations (hyperframes, revideo, shorts packaging) (27)

| Tool | Summary |
| --- | --- |
| `hyperframes_add_block` | Install a block from the Hyperframes catalog. |
| `hyperframes_benchmark` | Benchmark Hyperframes render speed and file size. |
| `hyperframes_capture` | Capture a website as editable Hyperframes components without provider captions. |
| `hyperframes_catalog` | Browse Hyperframes catalog blocks/components. |
| `hyperframes_compositions` | List compositions in a Hyperframes project. |
| `hyperframes_doctor` | Run Hyperframes environment diagnostics. |
| `hyperframes_info` | Print Hyperframes project metadata. |
| `hyperframes_init` | Scaffold a new Hyperframes project. |
| `hyperframes_inspect` | Inspect rendered composition layout for overflow and visual issues. |
| `hyperframes_preview` | Launch Hyperframes preview studio for live preview. |
| `hyperframes_remove_background` | Cut a person or a product out of a still or video. |
| `hyperframes_render` | Render a Hyperframes composition to video. |
| `hyperframes_snapshot` | Capture key frames as PNG screenshots for visual verification. |
| `hyperframes_still` | Render a single frame as image from a Hyperframes composition. |
| `hyperframes_to_mcpvideo` | Render a Hyperframes composition and post-process with mcp-video in one step. |
| `hyperframes_transcribe` | Transcribe audio/video to word-level timestamps or import transcripts. |
| `hyperframes_tts` | Generate speech audio or list available Hyperframes local TTS voices. |
| `hyperframes_validate` | Validate a Hyperframes project for rendering readiness. |
| `revideo_install` | Install the exact locked Revideo dependencies for a materialized project. |
| `revideo_materialize` | Materialize Kinocut's pinned Revideo project for a validated job. |
| `revideo_render` | Render and atomically publish a verified local Revideo artifact. |
| `revideo_render_job` | Materialize, install, render, and verify one local Revideo job. |
| `shorts_package` | Package approved platform renders from a saved plan. Never posts. |
| `shorts_plan_show` | Load a saved shorts plan and return source-free proposals for review. |
| `shorts_render` | Render platform drafts for an approved candidate from a saved plan. |
| `shorts_review` | Append one human review decision to a saved shorts plan (source-free). |
| `video_shorts` | Trim, caption, make vertical, and export selected segments in one call. |

### Not in a family (1)

| Tool | Summary |
| --- | --- |
| `search_tools` | Find registered MCP tools by name, keyword, or a supported task phrase. |

<!-- END GENERATED INDEX -->
