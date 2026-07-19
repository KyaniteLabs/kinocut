# MCP Tools Reference

kino exposes 142 registered MCP tools across video editing, governed AI-video review and salvage, project-backed deterministic inspection, dedicated rescue, post-rescue planning, the agent workflow engine, PUSHING CREATION-style planning, Hyperframes video authoring, repurposing packages, audio, effects, analysis, and image workflows. All return structured JSON with `success` and operation metadata. On failure, they return `{"success": false, "error": {...}}` with auto-fix suggestions. High-risk video/audio operations also run preflight guardrails that warn or fail early before FFmpeg can silently produce unusable output.

---

## Project-backed Inspection (3 tools)

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

## Governed AI-video Review and Salvage (4 tools)

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

## Meta / Discovery (1 tool)

| Tool | Description |
|------|-------------|
| `search_tools` | Search all registered MCP tools by keyword. Returns matching tool names, descriptions, and required parameters. Use this when you need to find the right tool without loading the full registry into context. |

**Python Client:**
```python
from kinocut import Client
editor = Client()
results = editor.search_tools("subtitle")
# Returns: {"success": True, "count": 3, "tools": [...]}
```

---

## Cinematic Creation (4 tools)

Plan video generation like a director of photography before rendering. These tools implement a PUSHING CREATION-compatible pre-production workflow: project scaffold, STYLE_/NEG_ blocks, storyboard tables, and prompt expansion.

| Tool | Description |
|------|-------------|
| `video_project_create` | Scaffold `projects/<slug>/style.md`, `storyboard.md`, and `refs/` using cinematic starter templates |
| `style_pack_read` | Parse STYLE_ and NEG_ blocks from `style.md` or a project directory |
| `storyboard_read` | Parse storyboard rows from `storyboard.md` or a project directory |
| `shot_prompt_render` | Expand one storyboard shot into `prompt` and `negative_prompt` strings for a generation provider |

---

## Agent Workflow Engine (4 tools)

Plan, validate, render, recover, and prove a multi-step local video job from one JSON
job-spec over a small allowlisted op set (`probe | trim | resize | convert | merge |
add_text`). Every op maps 1:1 to a vetted engine function; params are introspected from
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

## Dedicated Video Rescue (3 tools)

The rescue tools form one review-first local pipeline. Plan and inspect before render; pass
only IDs from the plan's `safe_repairs`; inspect the final receipt before trusting the
package. Full contracts and examples are in [RESCUE.md](RESCUE.md).

| Tool | Description |
|------|-------------|
| `video_rescue_plan` | Analyze one local video without rendering; return evidence, previews, policy-classified safe/recommended/unavailable/blocked work, package intents, and an estimate |
| `video_rescue_render` | Apply approved safe repair IDs from an immutable reviewed plan; fail closed on staleness, dependency drift, cancellation, or verification failure |
| `video_rescue_inspect` | Inspect a plan or receipt and re-check promoted artifact hashes, verification, privacy, resume, and cleanup state without modifying media |

---

## Post-Rescue Planning (8 tools)

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

## Core Editing (35 tools)

| Tool | Description |
|------|-------------|
| `video_info` | Get metadata: duration, resolution, codec, fps, file size |
| `video_info_detailed` | Extended metadata with scene detection and dominant colors |
| `video_trim` | Trim by start time + duration or end time |
| `video_merge` | Concatenate clips with optional per-pair transitions; warns on resolution/FPS/audio mismatches and rejects transitions longer than the shortest clip |
| `video_add_text` | Overlay text with positioning, font, color, shadow |
| `video_add_texts` | Overlay multiple text elements in a single FFmpeg pass; auto-detects overlaps and distributes stacked texts at the same named position |
| `video_add_audio` | Add, replace, or mix audio tracks with fade effects; validates volume and warns on timing/sample-rate risks |
| `video_resize` | Change resolution or apply preset aspect ratios (16:9, 9:16, 1:1, etc.) |
| `video_convert` | Convert between mp4, webm, gif, mov, hevc, av1, prores (two-pass encoding) |
| `video_speed` | Speed up or slow down (0.5x = slow-mo, 2x = time-lapse) |
| `video_reverse` | Reverse video and audio playback |
| `video_fade` | Fade in/out effects |
| `video_crop` | Crop to rectangular region with offset |
| `video_rotate` | Rotate 90/180/270 and flip horizontal/vertical |
| `video_filter` | Apply filters: blur, sharpen, grayscale, sepia, invert, brightness, contrast, saturation, denoise, deinterlace, ken_burns; numeric parameters are bounded/clamped before FFmpeg execution |
| `video_chroma_key` | Remove solid color background (green screen) with bounded similarity/blend parameters |
| `video_stabilize` | Stabilize shaky footage (requires FFmpeg with vidstab) |
| `video_subtitles` | Burn `.srt`/`.vtt`/authored `.ass` subtitles into video; optional `style` force_style override (omit to preserve authored ASS PlayRes/styles/positions). SRT/VTT are rendered dimension-aware via a synthesized ASS whose PlayResX/Y match the probed display size |
| `video_subtitles_styled` | Burn subtitles with custom styling (font, size, color, outline) |
| `video_generate_subtitles` | Create SRT from text entries, optionally burn in |
| `video_watermark` | Add image watermark with validated opacity and positioning |
| `video_overlay` | Picture-in-picture overlay with opacity and timing guardrails |
| `video_composite_layers` | Spec-driven ordered image/video layer compositing with transforms, timing windows, masks/mattes, full-canvas and allowlisted positioned blend modes (multiply/screen/overlay/darken/lighten), rotation with a `pivot` reference point, dry-run plans, and deterministic `layer_plan` v2 receipts (video-only output) |
| `video_split_screen` | Side-by-side or top/bottom layout with duration/FPS/audio mismatch warnings |
| `video_edit` | Full timeline-based edit from JSON DSL |
| `video_create_from_images` | Create video from image sequence |
| `video_export_frames` | Export video as individual image frames |
| `video_extract_frame` | Extract a single frame at a given timestamp for visual verification |
| `video_extract_audio` | Extract audio as mp3, wav, aac, ogg, or flac |
| `video_export` | Render with quality and format settings; optional C2PA signing for final MP4 exports via `c2pa_manifest_path` |
| `video_normalize_audio` | Normalize audio loudness to a target LUFS level |
| `video_batch` | Apply the same operation to multiple video files |
| `video_cleanup` | Remove Kinocut-managed intermediate files |
| `video_hls_segment` | Segment video into HLS format with multi-quality variants |
| `video_template_preview` | Preview social/video template operations before rendering |
| `video_validate_text_layout` | Validate text overlays for overlap, low contrast, unsafe positioning, and missing shadows before rendering |

For `video_composite_layers`, positioned non-`normal` blend requires explicit `width` and `height`, an integral nonnegative in-canvas `position`, full opacity, and no scale, rotation/pivot, mask/matte, or timing window. The compositor crops the running base, blends the same-size layer, and overlays the result back. Full-canvas blend remains supported; other geometry fails closed with `unsupported_blend_geometry`.

---

## AI-Powered (11 tools)

| Tool | Description | Dependencies |
|------|-------------|--------------|
| `video_analyze` | Comprehensive video analysis: transcript, metadata, scenes, audio, quality, chapters, and colors | FFmpeg; optional Whisper/image extras |
| `video_ai_remove_silence` | Auto-remove silent sections with configurable threshold | FFmpeg |
| `video_ai_transcribe` | Speech-to-text with timestamp alignment | [openai-whisper](https://pypi.org/project/openai-whisper/) |
| `video_ai_scene_detect` | ML-enhanced scene change detection (perceptual hashing) | [imagehash](https://pypi.org/project/imagehash/), Pillow |
| `video_ai_stem_separation` | Isolate vocals, drums, bass, other instruments | [demucs](https://pypi.org/project/demucs/), Torch, TorchAudio, TorchCodec |
| `video_ai_upscale` | AI super-resolution upscaling (2x or 4x) | [opencv-contrib-python](https://pypi.org/project/opencv-contrib-python/); Real-ESRGAN/BasicSR where supported |
| `video_ai_color_grade` | Auto color grading with style presets or reference matching | FFmpeg |
| `video_quality_check` | Check brightness, contrast, saturation, audio levels, color balance |
| `video_design_quality_check` | Full design quality analysis: layout, typography, color, motion, composition |
| `video_fix_design_issues` | Auto-fix brightness, contrast, saturation, and audio level issues |
| `video_release_checkpoint` | Hard quality gate plus thumbnail/storyboard artifacts before publishing |

Install only the AI dependencies you need:

```bash
pip install "kinocut[transcribe]"  # Whisper transcription
pip install "kinocut[ai-scene]"    # perceptual scene hashing
pip install "kinocut[stems]"       # Demucs stem separation
pip install "kinocut[upscale]"     # OpenCV upscaling; Real-ESRGAN/BasicSR where supported
pip install "kinocut[ai]"          # all AI extras, kept for compatibility
pip install yt-dlp                   # only for downloading platform URLs (YouTube/Vimeo/...)
```

---

## Hyperframes — HTML-Native Video (18 tools)

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
| `hyperframes_remove_background` | Remove image/video backgrounds to transparent media |
| `hyperframes_doctor` | Run Hyperframes environment diagnostics |
| `hyperframes_benchmark` | Compare render speed and output size, with configurable run count |
| `hyperframes_compositions` | List all compositions in a project |
| `hyperframes_preview` | Launch Hyperframes preview studio |
| `hyperframes_validate` | Check project structure and run lint |
| `hyperframes_add_block` | Install a block from the Hyperframes catalog, with optional clipboard suppression |
| `hyperframes_to_mcpvideo` | Pipeline: render with Hyperframes, then post-process with Kinocut |

---

## Repurposing (2 tools)

Create local YouTube/social media packages from one source video. Publishing and scheduling are intentionally out of scope for v1; the tools produce files, manifests, thumbnails, storyboards, and optional release-checkpoint artifacts for a human or downstream publisher to review.

| Tool | Description |
|------|-------------|
| `video_repurpose_plan` | Dry-run a platform manifest with vertical, horizontal, and square output variants |
| `video_repurpose` | Render platform-ready assets plus thumbnails, storyboards, release-checkpoint artifacts, and `repurpose_manifest.json` |

---

## Audio Synthesis (9 tools)

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
| `video_duck_audio` | Mix background music under a video's voice with automatic sidechain ducking; music dips while speech plays and recovers in pauses |
| `video_audio_bed` | Governed one-shot audio-bed: duck a music bed under a voice track, normalize to EBU R128 `target_lufs`, optionally loop with crossfade, and emit a deterministic edit-receipt (`AudioBedReceipt`, `operation: "audio_bed"`, fixed `keep_video` duration policy). The receipt lands at top-level `result["receipt"]`; no authorization, duration-policy, or duration-tolerance parameter is exposed. |

---

## Visual Effects (8 tools)

| Tool | Description |
|------|-------------|
| `effect_vignette` | Darken edges for cinematic focus |
| `effect_chromatic_aberration` | RGB color separation (glitch aesthetic) |
| `effect_scanlines` | Retro CRT scanline effect with flicker |
| `effect_noise` | Film grain and digital noise |
| `effect_glow` | Bloom/glow for highlights |
| `video_apply_mask` | Apply image mask with edge feathering |
| `video_luma_key` | Mask out dark regions based on luminance (brightness) |
| `video_shape_mask` | Apply geometric shape mask: circle, rounded_rect, oval |

---

## Transitions (3 tools)

| Tool | Description |
|------|-------------|
| `transition_glitch` | RGB shift + noise for digital distortion |
| `transition_pixelate` | Block dissolve with configurable pixel size |
| `transition_morph` | Mesh warp transition |

---

## Glitch Effects (12 tools)

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

## Layout & Motion Graphics (6 tools)

| Tool | Description |
|------|-------------|
| `video_layout_grid` | Grid layout for multiple videos (2x2, 3x1, etc.) with clip-count and duration mismatch warnings |
| `video_layout_pip` | Picture-in-picture with border and positioning |
| `video_text_animated` | Animated text overlays (fade, slide, typewriter) with color, timing, and overflow guardrails |
| `video_mograph_count` | Animated number counter video |
| `video_mograph_progress` | Progress bar/circle/dots animation |
| `video_auto_chapters` | Auto-detect scenes and create chapter timestamps |

---

## Analysis (8 tools)

| Tool | Description |
|------|-------------|
| `video_detect_scenes` | Auto-detect scene changes with threshold control |
| `video_thumbnail` | Extract a single frame (thumbnail / frame grab) at any timestamp |
| `video_preview` | Generate fast low-res preview |
| `video_storyboard` | Extract key frames as a grid for review |
| `video_compare_quality` | Compare PSNR/SSIM quality metrics between videos |
| `video_read_metadata` | Read video metadata tags |
| `video_write_metadata` | Write video metadata tags |
| `video_audio_waveform` | Extract audio waveform peaks and silence regions |

---

## Image Analysis (3 tools)

| Tool | Description |
|------|-------------|
| `image_extract_colors` | Extract dominant colors from an image or video frame via K-means clustering (1-20 colors) |
| `image_generate_palette` | Generate color harmony palette from an image or video frame |
| `image_analyze_product` | Analyze a product image or video frame — extract colors + optional AI description (Claude Vision) |
