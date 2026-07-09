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
| `normalize-audio` | Normalize audio-only or video input to a LUFS target |
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
| `audio-compose` | Layer audio tracks, including PCM WAV in legacy or extensible containers |
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
| `composite-layers` | Spec-driven ordered image/video layer compositing with transforms, masks, timing windows, full-canvas blend modes, rotation/pivot, dry-run plans, and `layer_plan` v2 receipts |


### `composite-layers` spec

```bash
mcp-video composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
mcp-video composite-layers --spec layers.json -o out.mp4 --save-layer-plan layer-plan.json
```

```json
{
  "canvas": {"width": 1280, "height": 720, "background": "#000000", "fps": 24, "duration": 2.0},
  "layers": [
    {"id": "background", "type": "video", "src": "bg.mp4", "opacity": 1.0, "position": {"x": 0, "y": 0}},
    {
      "id": "plate",
      "type": "image",
      "src": "plate.png",
      "mask": "plate-mask.png",
      "opacity": 1.0,
      "transform": {"x": 120, "y": 80, "width": 640},
      "start": 0.25,
      "duration": 1.5
    },
    {"id": "title", "type": "image", "src": "title.png", "opacity": 0.9, "position": {"x": 32, "y": 32}}
  ],
  "output": {"format": "mp4"}
}
```

The compositor supports normal alpha compositing, per-layer opacity, fixed x/y positioning, `transform.width`, `transform.height`, `transform.scale`, `start`/`duration` timing windows, image/video/solid layers, and optional `mask`/`matte` alpha sources. It also supports **full-canvas** blend modes (`multiply`, `screen`, `overlay`, `darken`, `lighten` — a non-`normal` blend layer must be full-canvas: position `{0,0}`, full opacity, no scale/mask/timing, else it fails closed with `unsupported_blend_geometry`) and **rotation** (`rotation` in degrees within `[-360, 360]` with a new `pivot` reference point — `center` default, `top_left`, `top_right`, `bottom_left`, `bottom_right`; ordering is scale → rotate → opacity → position). The existing `anchor` field stays a position alias, distinct from `pivot`. Output is video-only (`audio_policy: dropped_video_only`). Relative `src`, `mask`, and `matte` paths resolve relative to the spec file and must stay inside that directory. Positioned/scaled/masked/timed blend, rotation + mask, and per-layer effect routing are deferred and fail closed.

## Workflow Engine

Plan, validate, render, recover, and prove a multi-step local video job from one JSON
job-spec. Flat commands map 1:1 to the `video_workflow_*` MCP tools. Full schema, `@ref`
grammar, variants, resume, and cleanup are in [WORKFLOWS.md](WORKFLOWS.md).

| Command | Description |
|---------|-------------|
| `workflow-validate` | Fail-closed structural gate for a job-spec; renders nothing |
| `workflow-plan` | No-render plan (op graph, source probes/hashes) for a job-spec |
| `workflow-render` | Execute a job-spec sequentially and emit a provenance receipt |
| `workflow-inspect` | Summarize any workflow/`layer_plan` receipt with a read-only integrity check |

```bash
mcp-video workflow-validate --spec job.json
mcp-video workflow-plan     --spec job.json [--save-plan plan.json] [--variant square]
mcp-video workflow-render   --spec job.json [--resume receipt.json] [--save-receipt receipt.json] \
                            [--keep-intermediates] [--variant square] [--all-variants] [--save-receipt-dir receipts/]
mcp-video workflow-inspect  --receipt receipt.json
```

| Flag | Command | Description |
|------|---------|-------------|
| `--spec` | validate / plan / render | Path to the workflow job-spec JSON file (required) |
| `--save-plan` | plan | Optional path to write the plan artifact as JSON |
| `--variant` | plan / render | Operate on one declared variant's effective steps |
| `--resume` | render | Path to a prior render receipt to resume from |
| `--save-receipt` | render | Optional path to write the workflow receipt as JSON |
| `--keep-intermediates` | render | Retain `@work` intermediates even on success |
| `--all-variants` | render | Render every declared variant and emit a batch summary (mutually exclusive with `--variant`) |
| `--save-receipt-dir` | render | With `--all-variants`, directory for per-variant receipts (`<dir>/<variant>.json`) |
| `--receipt` | inspect | Path to the receipt JSON file to inspect (required) |

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

Quality JSON identifies each saturation and contrast metric, its unit, measured value, and whether the measurement was available. Technical and design checks use the same definitions. `video-quality-check --fail-on-warning` is a CI-style gate: it exits nonzero when `all_passed` is false.

## Image Analysis

| Command | Description |
|---------|-------------|
| `image-extract-colors` | Extract dominant colors from an image |
| `image-generate-palette` | Generate color harmony palette |
| `image-analyze-product` | Analyze product image (colors + AI description) |

## Hyperframes Commands

| Command | Description |
|---------|-------------|
| `hyperframes-render` | Render a Hyperframes composition to video or PNG sequence (`--composition`, `--resolution`, `--variables`, `--variables-file`; width/height must map to a preset) |
| `hyperframes-compositions` | List compositions in a Hyperframes project |
| `hyperframes-preview` | Launch Hyperframes preview studio |
| `hyperframes-still` | Render a single frame as an image; accepts `--variables` and `--variables-file` runtime data |
| `hyperframes-snapshot` | Capture one or more rendered PNG snapshots; accepts `--variables` and `--variables-file` runtime data |
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

Hyperframes project paths may be relative or absolute. Relative paths are resolved once against the caller's working directory before the command is executed.

## Global Options

| Option | Description |
|--------|-------------|
| `--format text\|json` | Output format (default: text — rich tables & spinners) |
| `--version` | Show version and exit |
| `--mcp` | Run as MCP server (default when no command given) |
