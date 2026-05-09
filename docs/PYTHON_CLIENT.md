# Python Client Reference

```python
from mcp_video import Client

editor = Client()
```

## Agent-safe helpers

| Method | Returns | Description |
|--------|---------|-------------|
| `inspect(method_name)` | `dict` | Real signature, aliases, method category, and return type |
| `pipeline(steps, output_path?)` | `EditResult` | Chain media operations with `.output_path` propagation and guardrail warnings |
| `assert_quality(video, min_score?)` | `dict` | Hard quality gate; raises if quality is below threshold |
| `release_checkpoint(video, output_dir?, min_score?, frame_count?)` | `dict` | Hard quality gate plus thumbnail/storyboard review artifacts |

Media-producing methods return an `EditResult`-compatible object with `.output_path`.
Analysis methods return report models or dictionaries.

---

## Usage Examples

### Pipeline chaining

```python
from mcp_video import Client

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
checkpoint = client.release_checkpoint("final.mp4", min_score=0.8)
print(checkpoint["thumbnail"])      # Review thumbnail
print(checkpoint["storyboard"])     # Review key frames
print(checkpoint["quality_score"])  # Must pass min_score
```

---

## Core Editing Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `info(path)` | `VideoInfo` | Video metadata (duration, resolution, codec, fps, size) |
| `video_info_detailed(video)` | `dict` | Extended metadata with scene detection and dominant colors |
| `trim(input, start, duration?, end?, output?)` | `EditResult` | Trim by start time + duration or end time |
| `merge(clips, output?, transitions?, transition_duration?)` | `EditResult` | Concatenate clips with per-pair transitions |
| `add_text(video, text, position?, font?, size?, color?, shadow?, start_time?, duration?, output?)` | `EditResult` | Overlay text on video |
| `add_audio(video, audio, volume?, fade_in?, fade_out?, mix?, start_time?, output?)` | `EditResult` | Add or replace audio track |
| `resize(video, width?, height?, aspect_ratio?, quality?, output?)` | `EditResult` | Resize or change aspect ratio |
| `convert(video, format?, quality?, output?)` | `EditResult` | Convert format (mp4/webm/gif/mov) |
| `export(video, output?, quality?, format?)` | `EditResult` | Render with quality settings |
| `speed(video, factor?, output?)` | `EditResult` | Change playback speed |
| `reverse(video, output?)` | `EditResult` | Reverse video and audio playback |
| `fade(video, fade_in?, fade_out?, output?)` | `EditResult` | Video fade in/out effect |
| `crop(video, width, height, x?, y?, output?)` | `EditResult` | Crop to rectangular region |
| `rotate(video, angle?, flip_horizontal?, flip_vertical?, output?)` | `EditResult` | Rotate and/or flip video |
| `filter(video, filter_type, params?, output?)` | `EditResult` | Apply visual filter |
| `blur(video, radius?, strength?, output?)` | `EditResult` | Blur video |
| `color_grade(video, preset?, output?)` | `EditResult` | Apply color preset |
| `normalize_audio(video, target_lufs?, output?)` | `EditResult` | Normalize audio to LUFS target |
| `chroma_key(video, color?, similarity?, blend?, output?)` | `EditResult` | Remove solid color background |
| `stabilize(video, smoothing?, zoom?, output?)` | `EditResult` | Stabilize shaky footage |
| `overlay_video(background, overlay, position?, width?, opacity?, start_time?, duration?, output?)` | `EditResult` | Picture-in-picture overlay |
| `split_screen(left, right, layout?, output?)` | `EditResult` | Side-by-side or top/bottom layout |
| `edit(timeline, output?)` | `EditResult` | Execute full timeline edit from JSON |
| `create_from_images(images, fps?, output?)` | `EditResult` | Create video from images |
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
| `ai_color_grade(video, output, reference?, style?)` | `str` | Auto color grading |
| `ai_remove_silence(video, output, silence_threshold?, min_silence_duration?, keep_margin?)` | `str` | Auto-remove silent sections |

---

## Quality & Analysis Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `quality_check(video, fail_on_warning?)` | `dict` | Check brightness, contrast, saturation, audio levels, color balance |
| `design_quality_check(video, auto_fix?, strict?)` | `Any` | Full design quality analysis: layout, typography, color, motion, composition |
| `fix_design_issues(video, output?)` | `str` | Auto-fix brightness, contrast, saturation, and audio level issues |
| `detect_scenes(video, threshold?, output?)` | `SceneDetectionResult` | Auto-detect scene changes |
| `thumbnail(video, timestamp?, output?)` | `ThumbnailResult` | Extract single frame |
| `extract_frame(video, timestamp?, output?)` | `ThumbnailResult` | Alias for `thumbnail` |
| `preview(video, output?, scale_factor?)` | `EditResult` | Fast low-res preview |
| `storyboard(video, output_dir?, frame_count?)` | `StoryboardResult` | Key frames + grid |
| `compare_quality(video, reference, output?)` | `QualityMetricsResult` | Compare PSNR/SSIM metrics |
| `read_metadata(video)` | `MetadataResult` | Read video metadata tags |
| `write_metadata(video, metadata, output?)` | `EditResult` | Write video metadata tags |
| `audio_waveform(video, bins?)` | `WaveformResult` | Extract audio waveform |
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
| `text_animated(video, text, output, animation?, font?, size?, color?, position?, start?, duration?)` | `EditResult` | Animated text overlays |
| `mograph_count(start, end, duration, output, style?, fps?)` | `EditResult` | Animated number counter video |
| `mograph_progress(duration, output, style?, color?, track_color?, fps?)` | `EditResult` | Progress bar/circle/dots animation |

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

| Method | Returns | Description |
|--------|---------|-------------|
| `hyperframes_render(project_path, output?, fps?, width?, height?, composition?, quality?, format?, resolution?, workers?, crf?)` | `HyperframesRenderResult` | Render a Hyperframes composition to video or PNG sequence; width/height must map to Hyperframes resolution presets |
| `hyperframes_compositions(project_path)` | `CompositionsResult` | List compositions in a project |
| `hyperframes_preview(project_path, port?)` | `HyperframesPreviewResult` | Launch live preview studio |
| `hyperframes_still(project_path, output?, frame?)` | `HyperframesStillResult` | Render a single frame |
| `hyperframes_snapshot(project_path, frames?, at?)` | `HyperframesSnapshotResult` | Capture actual PNG snapshot paths |
| `hyperframes_inspect(project_path, samples?, strict?)` | `HyperframesJsonResult` | Inspect rendered layout issues |
| `hyperframes_info(project_path)` | `HyperframesJsonResult` | Read project metadata |
| `hyperframes_catalog(item_type?, tag?)` | `HyperframesJsonResult` | Browse blocks/components |
| `hyperframes_capture(url, output?)` | `HyperframesJsonResult` | Capture a website as editable components |
| `hyperframes_tts(text_or_file?, output?, list_voices?)` | `HyperframesJsonResult` | Generate local speech audio or list available voices |
| `hyperframes_transcribe(input_path, project_path?, model?, language?)` | `HyperframesJsonResult` | Transcribe media/import transcripts |
| `hyperframes_remove_background(input_path, output?)` | `HyperframesJsonResult` | Produce transparent cutout media |
| `hyperframes_doctor()` | `HyperframesJsonResult` | Run Hyperframes diagnostics |
| `hyperframes_benchmark(project_path, output?, runs?)` | `HyperframesJsonResult` | Benchmark render settings |
| `hyperframes_init(name, output_dir?, template?, video?, audio?, skip_transcribe?, model?, language?, tailwind?, resolution?)` | `HyperframesProjectResult` | Scaffold a new project |
| `hyperframes_add_block(project_path, block_name, no_clipboard?)` | `HyperframesBlockResult` | Install a block from the catalog |
| `hyperframes_validate(project_path)` | `HyperframesValidationResult` | Validate project for rendering readiness |
| `hyperframes_to_mcpvideo(project_path, post_process, output?)` | `HyperframesPipelineResult` | Render then post-process with mcp-video |

---

## Repurposing Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `repurpose_plan(video, output_dir?, platforms?)` | `dict` | Write a dry-run `repurpose_manifest.json` |
| `repurpose(video, output_dir?, platforms?, include_release_checkpoint?, min_score?)` | `dict` | Render platform-ready assets, thumbnails, storyboards, and checkpoint artifacts |

---

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

WaveformResult(success=True, peaks=[...], silence_regions=[...], bin_count=50)

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
