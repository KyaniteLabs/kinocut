# Python Client Reference

```python
from kinocut import Client

editor = Client()
```

`Client` runs the same engine as the MCP server and the `kino` CLI. Methods return
typed results or plain dicts and raise `MCPVideoError` subclasses (the class keeps its
former name) on failure. The [complete index](#complete-index) at the end lists every
public method, generated from the code; the sections below cover the ones used most.

`import kinocut` is lazy (PEP 562): it does not load `Client` or the engines until you
use them. `kinocut.Client is mcp_video.Client` holds for the compatibility import.

## Stream shorts (saved-plan stages)

```python
from kinocut import Client

client = Client()
client.shorts_plan_show("/path/to/plans")
client.shorts_review("/path/to/plans", candidate_id="candidate_01", decision="approve")
client.shorts_render("/path/to/plans", candidate_id="candidate_01")
client.shorts_package("/path/to/plans", candidate_id="candidate_01")
```

Commands fail closed without a current approve. See [STREAM_SHORTS.md](STREAM_SHORTS.md).

## Agent-safe helpers

| Method | Returns | Description |
|--------|---------|-------------|
| `inspect(method_name)` | `dict` | Real signature, aliases, method category, and return type |
| `pipeline(steps, output_path?)` | `EditResult` | Chain media operations with `.output_path` propagation and guardrail warnings |
| `assert_quality(video, min_score?)` | `dict` | Hard quality gate; raises if quality is below threshold |
| `release_checkpoint(video, output_dir?, min_score?, frame_count?)` | `dict` | Hard quality gate plus thumbnail/storyboard review artifacts |

Media-producing methods return an `EditResult`-compatible object with `.output_path`.
Analysis methods return report models or dictionaries.

## Project-backed Inspection Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `ingest(project_dir, source_path, lineage?, usage_rights_status?, usage_rights_evidence_ref?)` | `dict` | Ingest immutable bytes and validated generation/rights metadata |
| `preflight(project_dir, asset_id)` | `dict` | Resolve the active stored record and persist unified media preflight |
| `inspect_temporal(project_dir, asset_id, declared_regions?)` | `dict` | Build previews, sampled frames, declared-region crops, findings, manifest, and explicit provider availability |

```python
asset = editor.ingest("campaign-project", "incoming/clip.mov")
package = editor.inspect_temporal("campaign-project", asset["asset_id"])
print(package["inspection_manifest"])
```

The latter two methods require an existing project and accept only an `asset_id`, not an
arbitrary media path or caller-constructed record. `inspect_temporal` is intentionally
distinct from `inspect(method_name)`, which remains the client-introspection helper.

## Governed AI-video Methods

| Method | Returns | Purpose |
|--------|---------|---------|
| `verdict(project_dir, verdict)` | `dict` | Persist exact-asset analysis; approved dispositions require active exact human evidence |
| `acceptance_eval(project_dir, acceptance_spec_id, verdict_ids)` | `dict` | Resolve active records and derive acceptance from per-requirement, role, artifact, verdict, and defect evidence |
| `body_swap(project_dir, video_source, audio_source, output_path, *, duration_policy=None, authorization_decision_ids=None)` | `dict` | Require both source paths to resolve to active stored assets, replace video, and prove approved-audio preservation |
| `salvage(project_dir, source_asset_id, recipe, policy, acceptance_spec_id, *, authorization_decision_ids=None)` | `dict` | Create a lineage-bound derivative with a fresh review slot |

These are the same validated operations exposed by MCP and CLI. None accepts a force,
override, bypass, projectless body-swap, caller-built acceptance evidence, or
implicit-approval argument.

See [AI-video review and salvage](AI_VIDEO_REVIEW_AND_SALVAGE.md) for the complete safe
operating sequence and failure conditions.

## Post-Rescue Planning Methods

These methods accept a JSON-compatible request mapping and return a dictionary. They plan
or verify only and do not render media or perform network I/O.

| Method | Description |
|--------|-------------|
| `semantic_timeline(request)` | Build a source-time semantic timeline |
| `semantic_query(request)` | Query local source-backed spans |
| `timeline_edit_plan(request)` | Build an EDL and optional approval-bound diff |
| `visual_transform_plan(request)` | Plan analysis, reframing, or stabilization |
| `restoration_plan(request)` | Plan or evaluate restorative work |
| `composition_plan(request)` | Build or verify composition artifacts |
| `creative_autopilot_plan(request)` | Coordinate declared proven planners or abstain |
| `remote_egress_plan(request)` | Plan explicit remote egress without network I/O |

The complete operation contracts are in [POST_RESCUE_FEATURES.md](POST_RESCUE_FEATURES.md).

## 360 dual-cam assembly (published 1.14.0)

Propose → storyboard → approve → render a `360_assembly_plan` from a **stitched equirect MP4**.
Not a new MCP tool. `.insv` fails closed. See [360_ASSEMBLY.md](360_ASSEMBLY.md).

| Method | Returns | Description |
|--------|---------|-------------|
| `propose_360_assembly(source, *, goal?, preset?, layout?, aspect?, writer_kind?, director?, model?, base_url?, allow_cloud?, propose?, storyboard_dir?)` | `dict` | Probe + write a `proposed` plan. Never renders. |
| `storyboard_360_assembly(plan, output_dir)` | `dict` | Extract review stills per camera / sample time. |
| `decide_360_assembly(plan, decision, *, layout?)` | `dict` | `approve` / `accept` / `reject`. Optional layout override on approve. |
| `render_360_assembly(plan, output_path, *, work_dir?, allow_fail?, min_score?)` | `dict` | Requires `status=approved`. `v360` extract + split/switch/PiP/single. |

```python
from kinocut import Client

video = Client()
plan = video.propose_360_assembly(
    "/abs/path/x4-export.mp4",
    goal="desk 360 split 9:16",
    storyboard_dir="/abs/path/360-board",
)
approved = video.decide_360_assembly(plan, "approve")
receipt = video.render_360_assembly(approved, "/abs/path/desk-split.mp4")
```

Cloud directors need `allow_cloud=True`. Render without approve raises `human_apply_required`.

---

## Usage Examples

### Pipeline chaining

```python
from kinocut import Client

client = Client()

# Chain operations — each step receives the previous output_path
result = client.pipeline(
    [
        {"op": "trim", "start": "00:00:10", "duration": "00:00:30"},
        {"op": "resize", "aspect_ratio": "9:16"},
        {"op": "add_text", "text": "Subscribe!", "position": "bottom-center", "size": 48},
        {"op": "normalize_audio", "target_lufs": -14},
        {"op": "export", "quality": "high"},
    ],
    output_path="final.mp4",
)
print(result.output_path)
```

### AI analysis + extract highlights

```python
info = client.analyze_video("interview.mp4")
scenes = info["scenes"]  # Auto-detected scene changes

# Extract a thumbnail from each scene
for i, (start, end) in enumerate(scenes[:5]):
    client.thumbnail("interview.mp4", timestamp=start, output=f"scene_{i}.jpg")
```

### Generate audio and composite

```python
# Create a tech drone + success chimes
drone = client.audio_preset("drone-tech", "drone.wav", duration=20, intensity=0.3)
chime = client.audio_preset("chime-success", "chime.wav", intensity=0.6)

soundtrack = client.audio_compose(
    tracks=[
        {"file": drone, "volume": 0.3, "start": 0},
        {"file": chime, "volume": 0.8, "start": 5},
        {"file": chime, "volume": 0.8, "start": 15},
    ],
    duration=20,
    output="soundtrack.wav",
)
```

### Effects chain

```python
client.effect_vignette("raw.mp4", "vignette.mp4", intensity=0.4)
client.effect_glow("vignette.mp4", "glow.mp4", intensity=0.3)
client.transition_glitch("scene1.mp4", "scene2.mp4", "glitch.mp4", duration=0.5)
```

### Hyperframes workflow

```python
# Scaffold, render, post-process
project = client.hyperframes_init("my-video", template="warm-grain")
client.hyperframes_validate(project.project_path)
render = client.hyperframes_render(project.project_path, output="base.mp4")
client.add_text(render.output_path, text="EPISODE 1", position="top-center", output="final.mp4")
```

### Quality gate before publishing

```python
checkpoint = client.release_checkpoint("final.mp4", min_score=80)
print(checkpoint["thumbnail"])      # Review thumbnail
print(checkpoint["storyboard"])     # Review key frames
print(checkpoint["quality"]["overall_score"])  # Must pass min_score
print(checkpoint["thumbnail"], checkpoint["storyboard"]["frames"])
```

---

## Core Editing Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `info(path)` | `VideoInfo` | Video metadata (duration, resolution, codec, fps, size) |
| `video_info_detailed(video)` | `dict` | Extended metadata with scene detection and dominant colors |
| `trim(input, start, duration?, end?, output?, accurate?)` | `EditResult` | Trim by finite start time + duration or absolute end; staged output publication |
| `merge(clips, output?, transitions?, transition_duration?)` | `EditResult` | Concatenate clips with per-pair transitions |
| `add_text(video, text, position?, font?, size?, color?, shadow?, start_time?, duration?, output?)` | `EditResult` | Overlay text on video |
| `add_audio(video, audio, volume?, fade_in?, fade_out?, mix?, start_time?, output?, duration_policy?)` | `EditResult` | Add or replace audio; `loop_audio` is supported with mixing. [Contract](AUDIO_MIXING.md#loop-one-added-track) |
| `mix_audio(video, tracks, output?, keep_source?, audio_bitrate?)` | `EditResult` | Mix timed tracks in one AAC encode with picture copied. [Contract](AUDIO_MIXING.md) |
| `duck_audio(video, music, output?, music_volume?, threshold?, ratio?, attack?, release?)` | `EditResult` | Plain-file sidechain ducking; no governed audio-bed receipt or delivery normalization. [Contract](AUDIO_MIXING.md#duck-music-under-existing-speech) |
| `resize(video, width?, height?, aspect_ratio?, quality?, output?)` | `EditResult` | Resize or change aspect ratio |
| `convert(video, format?, quality?, output?)` | `EditResult` | Convert format (mp4/webm/gif/mov) |
| `export(video, output?, quality?, format?, c2pa_manifest_path?, c2pa_tool_path?, c2pa_signer_path?)` | `EditResult` | Render with quality settings; optionally C2PA-sign final MP4 output |
| `speed(video, factor?, output?)` | `EditResult` | Change playback speed with staged output publication |
| `reverse(video, output?)` | `EditResult` | Reverse video and audio playback |
| `fade(video, fade_in?, fade_out?, output?)` | `EditResult` | Video fade in/out effect |
| `crop(video, width, height, x?, y?, output?)` | `EditResult` | Crop in upright display pixels, including rotation-tagged phone video |
| `rotate(video, angle?, flip_horizontal?, flip_vertical?, output?)` | `EditResult` | Rotate and/or flip video |
| `filter(video, filter_type, params?, output?)` | `EditResult` | Apply bounded visual/audio filters; `noise_reduction` defaults to -50 dB, Ken Burns retains source frame rate by default |
| `blur(video, radius?, strength?, output?)` | `EditResult` | Blur video |
| `color_grade(video, preset?, output?)` | `EditResult` | Apply color preset |
| `normalize_audio(video, target_lufs?, output?)` | `EditResult` | Normalize audio/video to LUFS target; PCM16 WAV or AAC supported M4A/video output, staged validation and observed codec/container metadata |
| `chroma_key(video, color?, similarity?, blend?, output?)` | `EditResult` | Remove solid color background |
| `stabilize(video, smoothing?, zoom?, output?)` | `EditResult` | Stabilize shaky footage |
| `overlay_video(background, overlay, position?, width?, opacity?, start_time?, duration?, output?)` | `EditResult` | Picture-in-picture overlay |
| `split_screen(left, right, layout?, output?)` | `EditResult` | Side-by-side or top/bottom layout |
| `edit(timeline, output?)` | `EditResult` | Execute full timeline edit from JSON |
| `create_from_images(images?, fps?, output?, list_file?)` | `EditResult` | Create a frame-exact video from images or a list file (at most 18,000 images, fps at most 60) |
| `export_frames(video, fps?, output_dir?)` | `ImageSequenceResult` | Export video as frames |
| `extract_audio(video, output?, format?)` | `EditResult` | Extract audio as file path |
| `subtitles(video, subtitle_file, output?)` | `EditResult` | Burn subtitles into video |
| `text_subtitles(video, subtitles, output?, style?)` | `EditResult` | Burn subtitles with custom styling |
| `subtitles_styled(video, subtitles, output?, style?)` | `EditResult` | Alias for `text_subtitles` |
| `watermark(video, image, position?, opacity?, margin?, output?)` | `EditResult` | Add image watermark |
| `batch(inputs, operation, params?)` | `dict` | Apply operation to multiple files |

---

## AI Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `analyze_video(video, *, whisper_model?, language?, scene_threshold?, include_transcript?, include_scenes?, include_audio?, include_quality?, include_chapters?, include_colors?, output_srt?, output_txt?, output_md?, output_json?)` | `dict` | Comprehensive analysis: transcript, metadata, scenes, audio, quality, chapters, colors |
| `ai_transcribe(video, output_srt?, model?, language?)` | `dict` | Speech-to-text with Whisper |
| `ai_scene_detect(video, threshold?, use_ai?)` | `list[dict]` | Scene change detection |
| `ai_stem_separation(video, output_dir, stems?, model?)` | `dict[str, str]` | Isolate vocals, drums, bass, other with Demucs |
| `ai_upscale(video, output, scale?, model?)` | `str` | AI super-resolution upscaling |
| `ai_color_grade(video, output, reference?, style?, lut_path?)` | `str` | Color grade with a style, reference or explicit `.cube` LUT |
| `ai_remove_silence(video, output, silence_threshold?, min_silence_duration?, keep_margin?)` | `str` | Auto-remove silent sections |

---

## Quality & Analysis Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `quality_check(video, fail_on_warning?)` | `dict` | Check brightness, contrast, saturation, audio levels, color balance |
| `design_quality_check(video, auto_fix?, strict?)` | `Any` | Full design quality analysis: layout, typography, color, motion, composition |
| `fix_design_issues(video, output?)` | `str` | Auto-fix brightness and saturation issues (audio is not changed; use `normalize_audio`) |
| `detect_scenes(video, threshold?, output?)` | `SceneDetectionResult` | Auto-detect scene changes |
| `thumbnail(video, timestamp?, output?)` | `ThumbnailResult` | Extract single frame |
| `extract_frame(video, timestamp?, output?)` | `ThumbnailResult` | Alias for `thumbnail` |
| `preview(video, output?, scale_factor?)` | `EditResult` | Fast low-res preview |
| `storyboard(video, output_dir?, frame_count?)` | `StoryboardResult` | Key frames + grid |
| `compare_quality(video, reference, output?)` | `QualityMetricsResult` | Compare PSNR/SSIM metrics |
| `read_metadata(video)` | `MetadataResult` | Read video metadata tags |
| `write_metadata(video, metadata, output?)` | `EditResult` | Write video metadata tags |
| `audio_waveform(video, bins?)` | `WaveformResult` | Measure video/audio-only first-stream RMS dBFS bins; inspect `synthetic` before using level/silence data. [Contract](QUALITY_EVIDENCE.md#audio-waveform) |
| `auto_chapters(video, threshold?)` | `list[tuple[float, str]]` | Auto-detect scenes and create chapter timestamps |
| `generate_subtitles(entries, output?, burn?)` | `SubtitleResult` | Create SRT subtitles |

---

## Audio Synthesis Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `audio_synthesize(output, waveform?, frequency?, duration?, volume?, effects?)` | `EditResult` | Generate waveforms: sine, square, sawtooth, triangle, noise |
| `audio_preset(preset, output?, pitch?, duration?, intensity?)` | `EditResult` | 15 pre-configured sounds: UI blips, ambient drones, notification chimes |
| `audio_sequence(sequence, output)` | `EditResult` | Compose timed audio events into a layered track |
| `audio_compose(tracks, duration, output)` | `EditResult` | Mix multiple WAV tracks with volume control |
| `audio_effects(input_path, output, effects)` | `EditResult` | Apply effects chain: lowpass, reverb, normalize, fade |
| `add_generated_audio(video, audio_config, output)` | `EditResult` | Generate audio and add it to a video |
| `audio_spatial(video, output, positions, method?)` | `EditResult` | 3D spatial audio positioning |
| `audio_bed(voice_source, music_path, output_path, *, loop?, loop_crossfade?, fade_in?, fade_out?, target_lufs?, duck_threshold?, duck_ratio?, duck_attack?, duck_release?, music_volume?, save_receipt?)` | `dict` | Governed one-shot audio-bed: duck a music bed under the voice track, normalize to EBU R128, loop with crossfade, and emit a deterministic `AudioBedReceipt` (operation `"audio_bed"`, fixed `keep_video` duration policy). The engine result dict is returned unchanged — `result["receipt"]` is top-level. The method mirrors `video_audio_bed` (MCP) and `audio-bed` (CLI); there is no authorization, duration-policy, or duration-tolerance parameter. |

---

## Visual Effects, Transitions & Layout Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `effect_vignette(video, output, intensity?, radius?, smoothness?)` | `EditResult` | Darken edges for cinematic focus |
| `effect_chromatic_aberration(video, output, intensity?, angle?)` | `EditResult` | RGB color separation (glitch aesthetic) |
| `effect_scanlines(video, output, line_height?, opacity?, flicker?)` | `EditResult` | Retro CRT scanline effect |
| `effect_noise(video, output, intensity?, mode?, animated?)` | `EditResult` | Film grain and digital noise |
| `effect_glow(video, output, intensity?, radius?, threshold?)` | `EditResult` | Bloom/glow for highlights |
| `apply_mask(video, mask, feather?, output?)` | `EditResult` | Apply image mask with feathering |
| `transition_glitch(clip1, clip2, output, duration?, intensity?)` | `EditResult` | RGB shift + noise transition |
| `transition_pixelate(clip1, clip2, output, duration?, pixel_size?)` | `EditResult` | Block dissolve transition |
| `transition_morph(clip1, clip2, output, duration?, mesh_size?)` | `EditResult` | Mesh warp transition |
| `layout_grid(clips, layout, output, gap?, padding?, background?)` | `EditResult` | Grid layout for multiple videos |
| `layout_pip(main, pip, output, position?, size?, margin?, rounded_corners?, border?, border_color?, border_width?)` | `EditResult` | Picture-in-picture with border |
| `composite_layers(spec, output?, save_layer_plan?, dry_run?)` | `EditResult` | Spec-driven ordered layer compositing with transforms, masks, timing windows, full-canvas and allowlisted positioned blend modes, rotation/pivot, dry-run plans, and `layer_plan` v2 receipts (video-only output) |
| `text_animated(video, text, output, animation?, font?, size?, color?, position?, start?, duration?)` | `EditResult` | Animated text overlays |
| `mograph_count(start, end, duration, output, style?, fps?)` | `EditResult` | Animated number counter video |
| `mograph_progress(duration, output, style?, color?, track_color?, fps?)` | `EditResult` | Progress bar/circle/dots animation |

Non-`normal` blends support opacity and `start`/`duration` windows in two geometries: full-canvas at `{0,0}` without explicit sizing, or a positioned rectangle with both positive integer `width` and `height` and an integral nonnegative in-canvas position. RGB blending avoids applying color arithmetic to subsampled chroma planes. Scale, rotation/pivot, mask/matte, fractional positions and out-of-canvas rectangles remain deferred and fail closed with `unsupported_blend_geometry`. Video layers and video masks begin at the declared layer start. Sources and masks must resolve inside the spec directory; put the spec in a common parent of its media. The existing `position`/`transform` receipt fields and additive `features.positioned_blend` remain available.

---

## Image Analysis Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `extract_colors(image_path, n_colors?)` | `ColorExtractionResult` | Extract dominant colors |
| `generate_palette(image_path, harmony?, n_colors?)` | `PaletteResult` | Generate color harmony palette |
| `analyze_product(image_path, use_ai?, n_colors?)` | `ProductAnalysisResult` | Extract colors + optional AI description |
| `search_tools(query)` | `dict` | Search MCP tools by keyword |

---

## Hyperframes Methods

Relative render and requested still output paths resolve from the caller working
directory. A requested still output is atomically copied independently of mutable
snapshots and contains PNG bytes; changing its extension does not transcode it.
Without an explicit output, the existing snapshot path may be replaced by a later
snapshot. Missing still artifacts are errors.


| Method | Returns | Description |
|--------|---------|-------------|
| `hyperframes_render(project_path, output?, fps?, width?, height?, composition?, quality?, format?, resolution?, workers?, crf?, variables?, variables_file?)` | `HyperframesRenderResult` | Render a Hyperframes composition to video or PNG sequence; width/height must map to Hyperframes resolution presets; `variables` or `variables_file` passes runtime data |
| `hyperframes_compositions(project_path)` | `CompositionsResult` | List compositions in a project |
| `hyperframes_preview(project_path, port?)` | `HyperframesPreviewResult` | Launch live preview studio |
| `hyperframes_still(project_path, output?, frame?, variables?, variables_file?)` | `HyperframesStillResult` | Render a single frame with optional runtime data |
| `hyperframes_snapshot(project_path, frames?, at?, variables?, variables_file?)` | `HyperframesSnapshotResult` | Capture actual PNG snapshot paths with optional runtime data |
| `hyperframes_inspect(project_path, samples?, strict?)` | `HyperframesJsonResult` | Inspect rendered layout issues |
| `hyperframes_info(project_path)` | `HyperframesJsonResult` | Read project metadata |
| `hyperframes_catalog(item_type?, tag?)` | `HyperframesJsonResult` | Browse blocks/components |
| `hyperframes_capture(url, output?)` | `HyperframesJsonResult` | Capture a website as editable components |
| `hyperframes_tts(text_or_file?, output?, list_voices?)` | `HyperframesJsonResult` | Generate local speech audio or list available voices |
| `hyperframes_transcribe(input_path, project_path?, model?, language?)` | `HyperframesJsonResult` | Transcribe media/import transcripts |
| `hyperframes_remove_background(input_path?, output?, background_output?, model?, info?, mask_interval?, …)` | `HyperframesJsonResult` | Cut a person (default) or a product/object (`model="birefnet-general"`). `info=True` lists models with no download. Guide: [PRODUCT_MATTE.md](PRODUCT_MATTE.md) |
| `hyperframes_doctor()` | `HyperframesJsonResult` | Run Hyperframes diagnostics |
| `hyperframes_benchmark(project_path, output?, runs?)` | `HyperframesJsonResult` | Benchmark render settings |
| `hyperframes_init(name, output_dir?, template?, video?, audio?, skip_transcribe?, model?, language?, tailwind?, resolution?)` | `HyperframesProjectResult` | Scaffold a new project |
| `hyperframes_add_block(project_path, block_name, no_clipboard?)` | `HyperframesBlockResult` | Install a block from the catalog |
| `hyperframes_validate(project_path)` | `HyperframesValidationResult` | Validate project for rendering readiness |
| `hyperframes_to_mcpvideo(project_path, post_process, output?)` | `HyperframesPipelineResult` | Render then post-process with Kinocut |

---

## Revideo methods (since 1.15.2)

```python
Client.revideo_materialize(dest, job, scene_source=None) -> dict
Client.revideo_install(project_dir, timeout=600) -> dict
Client.revideo_render(project_dir, output_path, timeout=900) -> RevideoRenderResult
Client.revideo_render_job(
    job,
    output_path,
    work_dir=None,
    scene_source=None,
    install_timeout=600,
    render_timeout=900,
) -> RevideoRenderResult
```

Materialize and install return `success` plus `project_dir`. Render methods
retain the detailed receipt: project and output paths, output and exact on-disk
job-file SHA-256 digests, observed width, height, fps, counted frames, duration, and
render time. `.mp4`, `.webm`, and `.mov` select the pinned exporter's MP4,
WebM, and ProRes 4444 modes respectively; Kinocut verifies the encoded identity
before publication. A custom scene is trusted executable
TypeScript. Dependency installation may access npm; rendering is local.

## Repurposing Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `repurpose_plan(video, output_dir?, platforms?)` | `dict` | Write a dry-run `repurpose_manifest.json` |
| `repurpose(video, output_dir?, platforms?, include_release_checkpoint?, min_score=80.0?)` | `dict` | Render platform-ready assets, thumbnails, storyboards, and checkpoint artifacts. Default `min_score` is `DEFAULT_QUALITY_GATE_SCORE` (80). Since 1.16.0, MCP `video_repurpose` is a durable job and applies `min_score` before job success; the worker enforces its frozen checkpoint policy. 1.15.3 did not. |
| `shorts_package(..., allow_fail=False?)` | `dict` | Package approved shorts renders. Quality gate fails closed unless `allow_fail=True`. |

---

## Dedicated Video Rescue Methods

The Python client mirrors the review-first MCP and CLI rescue contract. Inspect the plan
before render and pass only IDs from `safe_repairs`. Full policy, package, cancellation,
resume, and error details are in [RESCUE.md](RESCUE.md).

| Method | Returns | Description |
|--------|---------|-------------|
| `rescue_plan(source, output_dir, save_plan?, policy?)` | `dict` | Local diagnosis, previews, dispositions, package intents, capabilities, and estimate; renders nothing |
| `rescue_render(plan, approved_repair_ids?, save_receipt?, resume_receipt?, cancel_file?, keep_intermediates?)` | `dict` | Apply approved safe repairs and return a verified package receipt |
| `rescue_inspect(receipt)` | `dict` | Read a plan or receipt and re-check package integrity without modifying media |

```python
from kinocut import Client

video = Client()
plan = video.rescue_plan("media/clip.mov", "rescue-output", "rescue-output/plan.json")

# Present every disposition and preview before selecting safe repair IDs.
approved = [repair["id"] for repair in plan["safe_repairs"]]
receipt = video.rescue_render(
    "rescue-output/plan.json",
    approved_repair_ids=approved,
    save_receipt="rescue-output/render-receipt.json",
)
inspection = video.rescue_inspect("rescue-output/render-receipt.json")
```

`approved_repair_ids=None` applies all safe repairs from an already reviewed plan. It never
applies recommendations. Missing local Whisper produces explicit unavailable caption and
transcript artifacts rather than failing an otherwise valid rescue.

---

## Agent Workflow Engine Methods

Plan, validate, render, recover, and prove a multi-step local video job from one JSON
job-spec. Each method accepts the spec as a path **or** an inline `dict`, and returns the
structured artifact as a `dict`. Structural violations and failing render steps raise
`MCPVideoError` (fail-closed). Full schema, `@ref` grammar, variants, resume, and cleanup
are in [WORKFLOWS.md](WORKFLOWS.md); receipt shapes are in
[VIDEO_RECEIPT.md](VIDEO_RECEIPT.md).

| Method | Returns | Description |
|--------|---------|-------------|
| `workflow_validate(spec)` | `dict` | Fail-closed structural verdict (`{"valid": True, ...}`); renders nothing |
| `workflow_plan(spec, save_plan?, variant?)` | `dict` | Dry-run plan artifact (`receipt_kind: "workflow_plan"`): op graph, source probes/hashes, output intents; renders zero media |
| `workflow_render(spec, resume_receipt?, save_receipt?, keep_intermediates?, variant?, all_variants?, save_receipt_dir?)` | `dict` | Execute sequentially and return a `workflow` receipt, or a `workflow_batch` summary for `all_variants` |
| `workflow_inspect(receipt)` | `dict` | Normalized read-only summary + integrity re-check of any `workflow`/`workflow_plan`/`layer_plan` receipt (legacy v1 tolerated) |

```python
from kinocut import Client

video = Client()

video.workflow_validate("job.json")
plan = video.workflow_plan("job.json", save_plan="plan.json")
receipt = video.workflow_render("job.json", save_receipt="receipt.json")
summary = video.workflow_inspect("receipt.json")

# resume a job that failed with intermediates kept
video.workflow_render("job.json", resume_receipt="receipt.json", save_receipt="receipt.json")

# render every declared variant into its own receipt
batch = video.workflow_render("job.json", all_variants=True, save_receipt_dir="receipts/")
```

---

## Return Models

```python
VideoInfo(path, duration, width, height, fps, codec, audio_codec, ...)
# .resolution  -> "1920x1080"
# .aspect_ratio -> "16:9"
# .size_mb -> 5.42

EditResult(success=True, output_path, duration, resolution, size_mb, format, operation, warnings=[])

ThumbnailResult(success=True, output_path, frame_path, timestamp)

StoryboardResult(success=True, output_path, frames=["f1.jpg", ...], grid="grid.jpg", count=8)

SceneDetectionResult(success=True, scenes=[(start, end), ...], scene_count=5)

ImageSequenceResult(success=True, frame_count=120, fps=30, duration=4.0, output_path)

SubtitleResult(success=True, output_path, srt_path, video_path, entry_count=15)

WaveformResult(success=True, duration=3.0, peaks=[...], mean_level=-24.7,
               max_level=-20.0, min_level=-120.0, silence_regions=[...], synthetic=False)

QualityMetricsResult(success=True, psnr=45.2, ssim=0.98)

MetadataResult(success=True, metadata={...})

ColorExtractionResult(success=True, colors=[...], n_colors=5)

PaletteResult(success=True, harmony="complementary", colors=[...])

ProductAnalysisResult(success=True, colors=[...], description="...")

HyperframesRenderResult(success=True, output_path, composition_id, duration)
HyperframesStillResult(success=True, output_path, frame)
HyperframesPreviewResult(success=True, url, port)
HyperframesProjectResult(success=True, project_path, template)
HyperframesBlockResult(success=True, project_path, block_name)
HyperframesValidationResult(success=True, valid, issues, warnings)
HyperframesPipelineResult(success=True, output_path, hyperframes_output, post_process)


```


## Local operation estimates (since 1.16.0)

`Client().estimate_operation("trim", duration_seconds=10, complexity=1)` returns the same dictionary as MCP `video_estimate_operation` and CLI `estimate`. Inputs must be finite, nonboolean numbers; duration is nonnegative and complexity positive. Arithmetic overflow and blank or oversized operation names are rejected. These are local heuristics with dimensionless cost units and `currency=None`, not measured latency or provider billing.

## Complete index

Every entry below is generated from the code, so nothing is missing. The sections above explain the important ones in depth.

<!-- BEGIN GENERATED INDEX -->
<!-- Generated by scripts/generate_reference_index.py; edit the code, then rerun it. -->

164 public methods.

| Method | Summary |
| --- | --- |
| `acceptance_eval()` | See MCP `video_acceptance_eval`: Evaluate exact-spec verdict and defect evidence without approving anything. |
| `add_audio()` | Add or replace audio track. |
| `add_generated_audio()` | Add generated audio to a video file. |
| `add_text()` | Overlay text on a video. |
| `ai_color_grade()` | Color grade video using a style, reference, or explicit .cube LUT. |
| `ai_remove_silence()` | Remove silent sections from video. |
| `ai_scene_detect()` | Detect scene changes in video. |
| `ai_stem_separation()` | Separate audio into stems using Demucs. |
| `ai_transcribe()` | Transcribe speech to text using Whisper. |
| `ai_upscale()` | Upscale video using AI super-resolution. |
| `analyze_product()` | Analyze a product image — extract colors and optionally generate AI description. |
| `analyze_video()` | Comprehensive video analysis — transcript, metadata, scenes, audio, quality, chapters, colors. |
| `apply_mask()` | Apply an image mask to a video with edge feathering. |
| `assert_quality()` | Raise if a video fails release-quality guardrails. |
| `audio_bed()` | Governed one-shot audio-bed: duck music under voice, normalize, receipt. |
| `audio_compose()` | Layer multiple audio tracks with mixing. |
| `audio_effects()` | Apply audio effects chain. |
| `audio_preset()` | Generate preset sound design elements. |
| `audio_sequence()` | Compose multiple audio events into a timed sequence. |
| `audio_spatial()` | Apply 3D spatial audio positioning. |
| `audio_synthesize()` | Generate audio procedurally using synthesis. |
| `audio_waveform()` | Extract audio waveform data (peaks and silence regions). |
| `auto_chapters()` | Auto-detect scene changes and create chapters. |
| `batch()` | Apply the same operation to multiple video files. |
| `benchmark_run()` | See MCP `video_benchmark_run`: Run the AI-video benchmark corpus against host capabilities. |
| `blur()` | Apply blur effect to a video. |
| `body_swap()` | See MCP `video_body_swap`: Replace video while preserving approved audio with explicit duration policy. |
| `capabilities()` | See MCP `video_capabilities`: Probe host capabilities (ffmpeg, whisper, c2pa) and return a capability report. |
| `chroma_key()` | Remove a solid color background (green screen / chroma key). |
| `color_grade()` | Apply a color grading preset to a video. |
| `compare_quality()` | Compare video quality between original and processed versions. |
| `composite_layers()` | Composite ordered image/video/solid layers from a JSON spec. |
| `composition_plan()` | See MCP `video_composition_plan`: Build source-backed manifests, selections, compositions, previews, and checks. |
| `convert()` | Convert video to a different format. |
| `cost_ledger()` | See MCP `video_cost_ledger`: Sum known USD cost events by category for the project. |
| `create_from_images()` | Create a frame-exact video from a sequence of images or a list file. |
| `creative_autopilot_plan()` | See MCP `video_creative_autopilot_plan`: Coordinate proven local planners or return a structured abstention. |
| `crop()` | Crop a video to a rectangular region. |
| `decide_360_assembly()` |  |
| `design_quality_check()` | Run comprehensive design quality analysis. |
| `detect_scenes()` | Detect scene changes in a video. |
| `duck_audio()` | Duck music against the video's audio on plain files, without a project store. |
| `edit()` | Execute a full timeline-based edit from JSON. |
| `effect_chromatic_aberration()` | Apply RGB channel separation effect. |
| `effect_glow()` | Apply bloom/glow effect for highlights. |
| `effect_noise()` | Apply film grain / digital noise. |
| `effect_scanlines()` | Apply CRT-style scanline overlay. |
| `effect_vignette()` | Apply vignette effect - darkened edges. |
| `estimate_operation()` | Estimate local wall time and dimensionless units, without rendering or billing. |
| `export()` | Render final video with quality settings. |
| `export_frames()` | Export frames from a video as images. |
| `extract_audio()` | Extract audio track from video. |
| `extract_colors()` | Extract dominant colors from an image using K-means clustering. |
| `extract_frame()` | Extract a frame from a video. Alias for thumbnail(). |
| `fade()` | Add fade in/out effect to a video. |
| `filter()` | Apply a visual filter to a video. |
| `fix_design_issues()` | Auto-fix brightness and saturation in a video; audio is not changed. |
| `generate_palette()` | Generate a color harmony palette from an image's dominant color. |
| `generate_subtitles()` | Generate SRT subtitles from text entries and optionally burn into video. |
| `hls_segment()` | Segment a video into HLS (HTTP Live Streaming) format. |
| `hyperframes_add_block()` | Install a block from the Hyperframes catalog. |
| `hyperframes_benchmark()` | Benchmark Hyperframes render speed and file size. |
| `hyperframes_capture()` | Capture a website as editable Hyperframes components. |
| `hyperframes_catalog()` | Browse Hyperframes catalog blocks/components. |
| `hyperframes_compositions()` | List compositions in a Hyperframes project. |
| `hyperframes_doctor()` | Run Hyperframes environment diagnostics. |
| `hyperframes_info()` | Return Hyperframes project metadata. |
| `hyperframes_init()` | Scaffold a new Hyperframes project. |
| `hyperframes_inspect()` | Inspect rendered layout for text/container overflow. |
| `hyperframes_preview()` | Launch Hyperframes preview studio for live preview. |
| `hyperframes_remove_background()` | Cut a person or a product out of a still or video. |
| `hyperframes_render()` | Render a Hyperframes composition to video. |
| `hyperframes_snapshot()` | Capture key frames as PNG screenshots for visual verification. |
| `hyperframes_still()` | Render a single frame as image. |
| `hyperframes_to_mcpvideo()` | Render a Hyperframes composition then post-process with Kinocut tools. |
| `hyperframes_transcribe()` | Transcribe media to word-level timestamps or import transcripts. |
| `hyperframes_tts()` | Generate local speech audio or list available Hyperframes TTS voices. |
| `hyperframes_validate()` | Validate project for rendering readiness. |
| `image_edit()` | Free establish-locked still edit with plan/receipt. |
| `info()` | Get metadata about a video file. |
| `ingest()` | See MCP `video_ingest`: Ingest immutable source bytes into an existing or new private project. |
| `inspect()` | Return method signature metadata for agents before calling. |
| `inspect_temporal()` | See MCP `video_inspect_temporal`: Build and persist the complete deterministic temporal evidence package. |
| `layout_grid()` | Create grid-based multi-video layout. |
| `layout_pip()` | Picture-in-picture overlay. |
| `learning_report()` | See MCP `video_learning_report`: Project a learning report (verdicts, defects, costs, recipes) from records. |
| `luma_key()` | Mask out dark regions based on luminance (brightness). |
| `merge()` | Merge multiple clips into one video. |
| `mix_audio()` | Mix timed tracks once, stream-copying picture and preserving video duration. |
| `mograph_count()` | Generate animated number counter video. |
| `mograph_progress()` | Generate progress bar / loading animation. |
| `normalize_audio()` | Normalize LUFS, loudness range, true peak and optional boundary fades. |
| `overlay_video()` | Picture-in-picture: overlay a video on top of another. |
| `pipeline()` | Run a simple chained media pipeline with EditResult normalization. |
| `preflight()` | See MCP `video_preflight`: Run unified technical, loudness, color, and decode preflight. |
| `preview()` | Generate a fast low-res preview. |
| `propose_360_assembly()` |  |
| `publish_gate()` | See MCP `video_publish_gate`: Evaluate the fail-closed publish gate; any blocking finding blocks publishing. |
| `quality_check()` | Run visual quality guardrails on a video. |
| `read_metadata()` | Read metadata tags from a video/audio file. |
| `recipe_capture()` | See MCP `video_recipe_capture`: Capture a workflow recipe (writer); idempotent by canonical digest. |
| `record_motion_acceptance()` | Create an explicit source-bound whole-film human-review receipt. |
| `release_checkpoint()` | Run a hard quality gate, then create human-review artifacts. |
| `remote_egress_plan()` | See MCP `video_remote_egress_plan`: Plan explicit remote egress and fake adapter receipts without network I/O. |
| `render_360_assembly()` |  |
| `repurpose()` | Render a local repurposing package. |
| `repurpose_plan()` | Create a dry-run repurposing manifest. |
| `rescue_inspect()` | Inspect a rescue plan or receipt without modifying artifacts. |
| `rescue_plan()` | Analyze ``source`` and return a policy-classified rescue plan. |
| `rescue_render()` | Render approved safe repairs from a reviewed rescue plan. |
| `resize()` | Resize a video or change aspect ratio. |
| `restoration_plan()` | See MCP `video_restoration_plan`: Plan or evaluate evidence-gated local restorative work. |
| `reverse()` | Reverse video and audio playback. |
| `revideo_install()` | See MCP `revideo_install`: Install the exact locked Revideo dependencies for a materialized project. |
| `revideo_materialize()` | See MCP `revideo_materialize`: Materialize Kinocut's pinned Revideo project for a validated job. |
| `revideo_render()` | See MCP `revideo_render`: Render and atomically publish a verified local Revideo artifact. |
| `revideo_render_job()` | See MCP `revideo_render_job`: Materialize, install, render, and verify one local Revideo job. |
| `review_decision()` | See MCP `video_review_decision`: Record a human review decision (writer); corrections supersede by record id. |
| `review_package()` | See MCP `video_review_package`: Assemble a review package and publish-gate verdict for a candidate artifact. |
| `rotate()` | Rotate and/or flip a video. |
| `salvage()` | See MCP `video_salvage`: Create one lineage-bound salvage derivative and a fresh review slot. |
| `search_tools()` | Search registered MCP tools by keyword. |
| `semantic_query()` | See MCP `video_semantic_query`: Query source-backed semantic spans locally without inventing descriptions. |
| `semantic_timeline()` | See MCP `video_semantic_timeline`: Build a local, source-time semantic timeline from supplied analyzer evidence. |
| `shape_mask()` | Apply a geometric shape mask (circle, rounded_rect, oval). |
| `shorts_package()` | Package approved platform renders from a saved plan. Never posts. |
| `shorts_plan_show()` | Load a saved shorts plan and return proposals without re-ingesting source. |
| `shorts_render()` | Render approved platform drafts from a saved plan. |
| `shorts_review()` | Append one human review decision to a saved shorts plan. |
| `sound_capabilities()` | Discover the public sound operation set. |
| `sound_master_render()` | Retain a two-pass master only after final measured policy compliance. |
| `sound_mix_render()` | Assemble supplied WAVs into a new ZIP; omit both arguments for a demo. |
| `sound_plan_validate()` | Validate a SoundPlan payload (or a built-in minimal plan). |
| `sound_qa_asr()` | Recognize supplied audio locally against a reference script. |
| `sound_qa_loudness()` | Measure supplied audio and report actual compliance; omit inputs for a demo. |
| `sound_voice_batch()` | Retain local caption speech from a request, or run the synthetic plan demo. |
| `speed()` | Change playback speed. |
| `split_screen()` | Place two videos side by side or top/bottom. |
| `stabilize()` | Stabilize a shaky video. |
| `still_gate()` | Fail-closed cohesion gate + contact sheet for a still package. |
| `still_grade()` | Ordered still grade: correct→match→look (optional LUT last). |
| `still_match()` | Match stills to a hero plate with shared WB/exposure gains. |
| `still_package()` | Package workflow: edit beats → match → grade → gate. |
| `storyboard()` | Extract key frames as storyboard for human review. |
| `storyboard_360_assembly()` |  |
| `subtitles()` | Burn subtitles into a video. |
| `subtitles_styled()` | Burn subtitles from SRT/VTT with styling (alias for text_subtitles). |
| `text_animated()` | Add animated text to video. |
| `text_subtitles()` | Burn subtitles from SRT/VTT with styling. |
| `thumbnail()` | Extract a frame from a video. |
| `timeline_edit_plan()` | See MCP `video_timeline_edit_plan`: Plan explicit or ordinary-person timeline edits as a reviewable EDL and diff. |
| `transition_glitch()` | Apply glitch transition between two video clips. |
| `transition_morph()` | Apply morph transition between two video clips. |
| `transition_pixelate()` | Apply pixelate transition between two video clips. |
| `trim()` | Trim a clip by start time and duration. |
| `verdict()` | See MCP `video_verdict`: Persist exact-asset analysis; approvals require active human evidence. |
| `video_info_detailed()` | Get extended video metadata. |
| `visual_transform_plan()` | See MCP `video_visual_transform_plan`: Plan subject/camera analysis, reframing, or stabilization with crop budgets. |
| `watermark()` | Add image watermark. |
| `workflow_inspect()` | Summarize any project receipt with a read-only integrity check. |
| `workflow_plan()` | Produce a no-render plan artifact for a workflow job-spec. |
| `workflow_render()` | Execute a workflow job-spec sequentially and return the receipt. |
| `workflow_validate()` | Validate a workflow job-spec without rendering any media. |
| `write_metadata()` | Write metadata tags to a video/audio file. |

<!-- END GENERATED INDEX -->
