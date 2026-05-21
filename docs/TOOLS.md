# MCP Tools Reference

mcp-video exposes structured MCP tools across video editing, PUSHING CREATION-style planning, Hyperframes 0.5 video authoring, repurposing packages, audio, effects, analysis, and image workflows. All return structured JSON with `success`, `output_path`, and operation metadata. On failure, they return `{"success": false, "error": {...}}` with auto-fix suggestions.

---

## Meta / Discovery (1 tool)

| Tool | Description |
|------|-------------|
| `search_tools` | Search all registered MCP tools by keyword. Returns matching tool names, descriptions, and required parameters. Use this when you need to find the right tool without loading the full registry into context. |

**Python Client:**
```python
from mcp_video import Client
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

## Core Editing (32 tools)

| Tool | Description |
|------|-------------|
| `video_info` | Get metadata: duration, resolution, codec, fps, file size |
| `video_info_detailed` | Extended metadata with scene detection and dominant colors |
| `video_trim` | Trim by start time + duration or end time |
| `video_merge` | Concatenate clips with optional per-pair transitions |
| `video_add_text` | Overlay text with positioning, font, color, shadow |
| `video_add_audio` | Add, replace, or mix audio tracks with fade effects |
| `video_resize` | Change resolution or apply preset aspect ratios (16:9, 9:16, 1:1, etc.) |
| `video_convert` | Convert between mp4, webm, gif, mov (two-pass encoding) |
| `video_speed` | Speed up or slow down (0.5x = slow-mo, 2x = time-lapse) |
| `video_reverse` | Reverse video and audio playback |
| `video_fade` | Fade in/out effects |
| `video_crop` | Crop to rectangular region with offset |
| `video_rotate` | Rotate 90/180/270 and flip horizontal/vertical |
| `video_filter` | Apply filters: blur, sharpen, grayscale, sepia, invert, brightness, contrast, saturation, denoise, deinterlace, ken_burns |
| `video_chroma_key` | Remove solid color background (green screen) |
| `video_stabilize` | Stabilize shaky footage (requires FFmpeg with vidstab) |
| `video_subtitles` | Burn SRT/VTT subtitles into video |
| `video_subtitles_styled` | Burn subtitles with custom styling (font, size, color, outline) |
| `video_generate_subtitles` | Create SRT from text entries, optionally burn in |
| `video_watermark` | Add image watermark with opacity and positioning |
| `video_overlay` | Picture-in-picture overlay |
| `video_split_screen` | Side-by-side or top/bottom layout |
| `video_edit` | Full timeline-based edit from JSON DSL |
| `video_create_from_images` | Create video from image sequence |
| `video_export_frames` | Export video as individual image frames |
| `video_extract_audio` | Extract audio as mp3, wav, aac, ogg, or flac |
| `video_export` | Render with quality and format settings |
| `video_normalize_audio` | Normalize audio loudness to a target LUFS level |
| `video_batch` | Apply the same operation to multiple video files |
| `video_cleanup` | Remove mcp-video-managed intermediate files |
| `video_hls_segment` | Segment video into HLS format with multi-quality variants |
| `video_template_preview` | Preview social/video template operations before rendering |

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
pip install "mcp-video[transcribe]"  # Whisper transcription
pip install "mcp-video[ai-scene]"    # perceptual scene hashing
pip install "mcp-video[stems]"       # Demucs stem separation
pip install "mcp-video[upscale]"     # OpenCV upscaling; Real-ESRGAN/BasicSR where supported
pip install "mcp-video[ai]"          # all AI extras, kept for compatibility
```

---

## Hyperframes — HTML-Native Video (18 tools)

Create videos programmatically using [Hyperframes](https://hyperframes.io/) — an HTML-native framework for video (Apache 2.0). Hyperframes owns HTML-video authoring, catalog blocks, website capture, local TTS, transcription import, background removal, layout inspection, diagnostics, benchmarking, and rendering; mcp-video wraps those operations for MCP-safe orchestration and FFmpeg post-processing.

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
| `hyperframes_to_mcpvideo` | Pipeline: render with Hyperframes, then post-process with mcp-video |

---

## Repurposing (2 tools)

Create local YouTube/social media packages from one source video. Publishing and scheduling are intentionally out of scope for v1; the tools produce files, manifests, thumbnails, storyboards, and optional release-checkpoint artifacts for a human or downstream publisher to review.

| Tool | Description |
|------|-------------|
| `video_repurpose_plan` | Dry-run a platform manifest with vertical, horizontal, and square output variants |
| `video_repurpose` | Render platform-ready assets plus thumbnails, storyboards, release-checkpoint artifacts, and `repurpose_manifest.json` |

---

## Audio Synthesis (7 tools)

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

## Layout & Motion Graphics (6 tools)

| Tool | Description |
|------|-------------|
| `video_layout_grid` | Grid layout for multiple videos (2x2, 3x1, etc.) |
| `video_layout_pip` | Picture-in-picture with border and positioning |
| `video_text_animated` | Animated text overlays (fade, slide, typewriter) |
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
