# CLI Reference

```
mcp-video [command] [options]
```

## Diagnostics

| Command | Description |
|---------|-------------|
| `doctor` | Check FFmpeg, Hyperframes, image, and AI dependencies |

## Core Editing

| Command | Description |
|---------|-------------|
| `info` | Get video metadata |
| `trim` | Trim a video |
| `merge` | Merge multiple clips |
| `add-text` | Overlay text on a video |
| `add-audio` | Add or replace audio track |
| `resize` | Resize or change aspect ratio |
| `convert` | Convert video format (with two-pass encoding) |
| `speed` | Change playback speed |
| `thumbnail` | Extract a single frame |
| `extract-frame` | Extract a single frame (with --time flag) |
| `preview` | Generate fast low-res preview |
| `storyboard` | Extract key frames as storyboard |
| `subtitles` | Burn subtitles into video |
| `generate-subtitles` | Create SRT subtitles from text |
| `watermark` | Add image watermark |
| `crop` | Crop to rectangular region |
| `rotate` | Rotate and/or flip video |
| `fade` | Add video fade in/out |
| `export` | Export with quality settings |
| `extract-audio` | Extract audio track |
| `edit` | Execute timeline-based edit from JSON (file path or inline) |
| `filter` | Apply visual filter (blur, sharpen, grayscale, ken_burns, etc.) |
| `blur` | Blur video |
| `color-grade` | Apply color preset (warm, cool, vintage, etc.) |
| `normalize-audio` | Normalize audio to LUFS target |
| `audio-waveform` | Extract audio waveform data |
| `reverse` | Reverse video playback |
| `chroma-key` | Remove solid color background (green screen) |
| `stabilize` | Stabilize shaky footage |
| `apply-mask` | Apply image mask with feathering |
| `detect-scenes` | Detect scene changes |
| `create-from-images` | Create video from image sequence |
| `export-frames` | Export video as image frames (--image-format for format) |
| `compare-quality` | Compare PSNR/SSIM quality metrics |
| `read-metadata` | Read video metadata tags |
| `write-metadata` | Write video metadata tags |
| `batch` | Apply operation to multiple files |
| `overlay-video` | Picture-in-picture overlay |
| `split-screen` | Place two videos side by side or top/bottom |
| `templates` | List available video templates |
| `template` | Apply a video template (tiktok, youtube-shorts, etc.) |
| `repurpose-plan` | Create a dry-run platform package manifest |
| `repurpose` | Render local platform-ready variants and review artifacts |

## Visual Effects

| Command | Description |
|---------|-------------|
| `effect-vignette` | Apply vignette (darkened edges) |
| `effect-glow` | Apply bloom/glow to highlights |
| `effect-noise` | Apply film grain or digital noise |
| `effect-scanlines` | Apply CRT-style scanlines overlay |
| `effect-chromatic-aberration` | Apply RGB channel separation |

## Transitions

| Command | Description |
|---------|-------------|
| `transition-glitch` | Glitch transition between two clips |
| `transition-morph` | Mesh warp morph transition |
| `transition-pixelate` | Pixel dissolve transition |

## AI Tools

| Command | Description |
|---------|-------------|
| `video-ai-transcribe` | Speech-to-text with Whisper |
| `video-ai-upscale` | AI super-resolution upscaling |
| `video-ai-stem-separation` | Separate audio stems with Demucs |
| `video-ai-scene-detect` | Scene detection with perceptual hashing |
| `video-ai-color-grade` | Auto color grading |
| `video-ai-remove-silence` | Remove silent sections |

## Audio Synthesis

| Command | Description |
|---------|-------------|
| `audio-synthesize` | Generate audio from waveform synthesis |
| `audio-compose` | Layer multiple audio tracks with mixing |
| `audio-preset` | Generate preset sound effects |
| `audio-sequence` | Compose timed audio event sequence |
| `audio-effects` | Apply audio effects chain (reverb, lowpass, etc.) |

## Motion Graphics

| Command | Description |
|---------|-------------|
| `video-text-animated` | Add animated text (fade, slide-up, typewriter) |
| `video-mograph-count` | Generate animated number counter |
| `video-mograph-progress` | Generate progress bar / loading animation |

## Layout

| Command | Description |
|---------|-------------|
| `video-layout-grid` | Arrange multiple videos in a grid |
| `video-layout-pip` | Picture-in-picture with border |

## Audio-Video

| Command | Description |
|---------|-------------|
| `video-add-generated-audio` | Add procedurally generated audio |
| `video-audio-spatial` | 3D spatial audio positioning |

## Quality & Analysis

| Command | Description |
|---------|-------------|
| `video-auto-chapters` | Auto-detect scene changes as chapters |
| `video-info-detailed` | Extended metadata with scene detection |
| `video-quality-check` | Visual quality checks (brightness, contrast, audio) |
| `video-design-quality-check` | Design quality analysis |
| `video-fix-design-issues` | Auto-fix design issues |

## Image Analysis

| Command | Description |
|---------|-------------|
| `image-extract-colors` | Extract dominant colors from an image |
| `image-generate-palette` | Generate color harmony palette |
| `image-analyze-product` | Analyze product image (colors + AI description) |

## Hyperframes Commands

| Command | Description |
|---------|-------------|
| `hyperframes-render` | Render a Hyperframes composition to video or PNG sequence (`--composition`, `--resolution`; width/height must map to a preset) |
| `hyperframes-compositions` | List compositions in a Hyperframes project |
| `hyperframes-preview` | Launch Hyperframes preview studio |
| `hyperframes-still` | Render a single frame as an image |
| `hyperframes-snapshot` | Capture one or more rendered PNG snapshots |
| `hyperframes-inspect` | Inspect rendered layout overflow and visual issues |
| `hyperframes-info` | Show Hyperframes project metadata |
| `hyperframes-catalog` | Browse catalog blocks and components |
| `hyperframes-capture` | Capture a website as editable Hyperframes components |
| `hyperframes-tts` | Generate local speech audio through Hyperframes |
| `hyperframes-transcribe` | Transcribe media or import transcript timing |
| `hyperframes-remove-background` | Remove image or video backgrounds |
| `hyperframes-doctor` | Run Hyperframes environment diagnostics |
| `hyperframes-benchmark` | Benchmark render settings (`--runs`) |
| `hyperframes-init` | Scaffold a new Hyperframes project (media bootstrap, Tailwind, and resolution flags) |
| `hyperframes-add-block` | Install a block from the Hyperframes catalog (`--no-clipboard`) |
| `hyperframes-validate` | Validate a Hyperframes project structure |
| `hyperframes-pipeline` | Render + post-process in one step |

## Global Options

| Option | Description |
|--------|-------------|
| `--format text\|json` | Output format (default: text — rich tables & spinners) |
| `--version` | Show version and exit |
| `--mcp` | Run as MCP server (default when no command given) |
