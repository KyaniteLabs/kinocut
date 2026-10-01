# CLI Reference

Development checkout: **203 MCP tools / 177 CLI commands**. Published 1.15.3:
**201 MCP tools / 173 CLI commands**. The additions below require this checkout.

```
kino [command] [options]
```

## Diagnostics

| Command | Description |
|---------|-------------|
| `doctor` | Check FFmpeg, Hyperframes, image, and AI dependencies. Optional `sphere_director` reports configured 360 director IDs (probe only; no network). |

## Project-backed Inspection

| Command | Description |
|---------|-------------|
| `video-ingest PROJECT SOURCE` | Ingest immutable source bytes plus optional `--lineage-json`, `--usage-rights-status`, and private `--usage-rights-evidence-ref` metadata |
| `video-preflight PROJECT ASSET_ID` | Persist unified technical, loudness, color, and decode preflight for the active asset |
| `video-inspect-temporal PROJECT ASSET_ID` | Build the complete temporal package; optional `--regions-json` declares bounded normalized text/logo crops |

Use `--format json` before the command for the same JSON-compatible envelope returned by
MCP and Python. Preflight and inspection never create a missing project and never accept an
arbitrary source path in place of a stored asset.

Development `record-motion-acceptance INPUT` records an explicit caller attestation:
provide `--report-json`, `--reviewer-id human:ID`, `--source-sha256`,
`--report-sha256`, `--watched-intervals-json`, `--dispositions-json`, and
`--verdict accept|reject`. These JSON arguments contain the exact report, complete
watched intervals, and every flagged interval's disposition. The receipt is nested
under `receipt`; `attestation_verified_by_system` remains false. Agents must not
invent viewing or act as human reviewers. This does not grant release approval.

## Governed AI-video Review and Salvage

| Command | Description |
|---------|-------------|
| `video-verdict PROJECT --verdict-json JSON` | Persist exact-asset analysis; approvals require active exact human evidence |
| `video-acceptance-eval PROJECT ACCEPTANCE_SPEC_ID [--verdict-id ID ...]` | Resolve active stored spec/verdict records and evaluate them without creating an approval |
| `video-body-swap PROJECT VIDEO_SOURCE AUDIO_SOURCE OUTPUT` | Require both inputs to be active stored project assets, then preserve approved audio under an explicit mismatch policy |
| `video-salvage PROJECT ASSET_ID RECIPE SPEC_ID --policy-json JSON` | Create a lineage-bound derivative and a fresh non-approved review slot |

All four commands use the same boundary as MCP and Python. There is no force, override,
or bypass flag. Repeat `--authorization-decision-id` only for stored human decisions.
Acceptance accepts record ids rather than caller-built verdict/spec objects, and body swap
never offers a projectless public mode.
See [AI-video review and salvage](AI_VIDEO_REVIEW_AND_SALVAGE.md) for the required ingest,
inspection, decision, protection, derivative, and re-review sequence.

## Intent, review, and cutfiles

Published surface (since 1.14.1; current 1.15.3). The existing intent/review commands
gain goal compilation and 360 handling in the
development checkout; there is no separate `kino 360` command.

| Command | Description |
|---------|-------------|
| `intent VERB` | Route a semantic intent verb to a dry-run plan. `--list` prints the catalog; `--params-json` supplies parameters. `--goal` compiles a reviewable cutfile; a 360 goal plus `--source` also proposes a source-bound `sphere_plan`. Neither renders. |
| `review-run INPUT` | Offline watching metric floor. |
| `review-decide REVIEW_RUN.json DECISION` | Watching accept/reject/revise. For a `360_assembly_plan` JSON artifact, explicit `accept` approves and optional `--output` renders through the shared engine; `reject` never renders, and `revise` is unsupported for sphere plans. |
| `cutfile-validate PATH` | Validate a cutfile JSON/YAML. |
| `cutfile-render PATH` | Render a cutfile via the workflow engine (`-o`, `--receipt`, `--keep-intermediates`). |
| `metric-qc INPUT` | Offline metric floor (duration / black / loudness). |
| `propose-broll SEGMENTS.json` | Transcript-keyed b-roll proposals (never silent insert). |
| `init PATH` | Scaffold a local project (`--name`, `--no-cutfile`). |
| `estimate OPERATION --duration SECONDS` | Dry-run local wall-time and dimensionless cost-unit heuristic; optional `--complexity`. Same engine as MCP `video_estimate_operation` and Python `Client.estimate_operation`; not billed dollars or a service latency guarantee. |

360 operator guide: [360_ASSEMBLY.md](360_ASSEMBLY.md). Save the nested `sphere_plan`
as its own JSON artifact before passing it to `review-decide`; inspect the plan and
obtain the human decision before invoking acceptance. Rendering rechecks source identity.

## Core Editing

| Command | Description |
|---------|-------------|
| `info` | Get video metadata |
| `trim` | Trim a video with finite times and staged output publication; `--accurate` selects slower frame-accurate seeking |
| `merge` | Merge multiple clips |
| `add-text` | Overlay text on a video |
| `add-audio` | Add/replace audio; `--mix --duration-policy loop_audio` loops the inserted track while preserving picture length; mixed `pad_audio` is unsupported |
| `resize` | Resize or change aspect ratio |
| `convert` | Convert video format; `--two-pass --target-bitrate KBPS` selects bitrate-based two-pass encoding for MP4/MOV |
| `speed` | Change playback speed with staged output publication |
| `thumbnail` | Extract a single frame |
| `extract-frame` | Extract a frame; omitted `--time` uses smart sampling when available, otherwise 10% of duration; explicit `--time 0` means the first frame |
| `preview` | Generate fast low-res preview |
| `storyboard` | Extract key frames as storyboard |
| `subtitles` | Burn `.srt`/`.vtt`/authored `.ass` subtitles into video; `--style` sets a force_style override (omit to preserve authored ASS styles/positions; SRT/VTT render dimension-aware) |
| `generate-subtitles` | Create SRT subtitles from text |
| `watermark` | Add image watermark |
| `crop` | Crop in upright display pixels; explicit odd dimensions reject, percentage crops derive even dimensions and preserve pixel offsets |
| `rotate` | Rotate and/or flip video |
| `fade` | Fade over the bounded primary-picture window, including delayed starts; a longer audio/container tail does not define the visible fade. Optional `--crf` controls encoding quality |
| `export` | Export with quality settings; optional C2PA signing via `--c2pa-manifest` for final MP4s |
| `extract-audio` | Extract audio track |
| `mix-audio INPUT --sounds JSON` | Mix timed tracks (`path`, `start`, `volume`, `fade_in`, `fade_out`); `--tracks` aliases `--sounds`, `--no-keep-source` omits original audio, `--audio-bitrate` sets AAC bitrate, `-o` sets output. One AAC encode and picture stream copy; gains can clip |
| `duck-audio INPUT MUSIC` | Sidechain duck music under existing audio; `--music-volume`, `--threshold`, `--ratio`, `--attack`, `--release`, `-o`. Attack/release are milliseconds; no loudness normalization or governed audio-bed receipt |
| `hls-segment INPUT` | Create local HLS assets; `--output-dir`, `--segment-duration`, `--playlist-name`, `--qualities low medium high ultra`. Packaging does not host or publish the files |
| `edit` | Execute timeline-based edit from JSON (file path or inline) |
| `filter` | Apply visual/audio filters; Ken Burns defaults to one frame per input, noise reduction defaults to -50 dB with `noise_level` override |
| `blur` | Blur video |
| `color-grade` | Apply color preset (warm, cool, vintage, etc.) |
| `normalize-audio` | Normalize audio-only or video input; `--lufs`, `--lra`, `--true-peak-dbtp`, `--fade-seconds` control loudness and boundary fades. WAV uses PCM16; supported M4A/video uses AAC with staged full-decode validation |
| `audio-waveform` | Measure first-stream RMS dBFS bins and silence; inspect `synthetic` in JSON output. [Evidence contract](QUALITY_EVIDENCE.md#audio-waveform) |
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
| `repurpose` | Render local platform-ready variants and review artifacts. Default `--min-score` is 80. Pass `--min-score 0` or `--skip-release-checkpoint` to skip the hard gate. Candidate MCP `video_repurpose` is a durable job and applies `min_score` before job success; its frozen checkpoint policy is enforced by the worker. Historical 1.15.3 did not enforce this policy. |
| `shorts-plan-show` | Show proposals from a saved shorts plan (source-free) |
| `shorts-review` | Append a human review decision to a saved shorts plan |
| `shorts-render` | Render approved platform drafts from a saved shorts plan |
| `shorts-package` | Package approved platform renders from a saved shorts plan. Fails closed on quality unless `--allow-fail`. |
| `sound-capabilities` | Discover the bounded public sound operation set |
| `sound-plan-validate` | Validate a SoundPlan JSON payload (`--plan-json` optional); explicit empty or invalid plans fail. See [input validation](SOUND_INPUT_VALIDATION.md). |
| `sound-voice-batch` | Retained local caption speech (`--request-json`, `--project-root`) with V2 [dry/distance profiles](SOUND_SPEECH_SPATIAL.md); legacy synthetic demo (`--plan-json` optional). See [caption speech](SOUND_DUB_REQUESTS.md). |
| `sound-mix-render` | Supplied-media mix ZIP with [routing](SOUND_ROUTING_REQUESTS.md), [automation](SOUND_AUTOMATION_REQUESTS.md), [sends](SOUND_SEND_REQUESTS.md), [sidechains](SOUND_SIDECHAIN_REQUESTS.md), [layers/loop fill/ducking](SOUND_LAYER_REQUESTS.md) and V4 [source-rate conversion](SOUND_RATE_CONVERSION.md), via `--request-json` and `--project-root`; omit both for a labelled demo. See [request contract](SOUND_MIX_REQUESTS.md). |
| `sound-qa-loudness` | Actual first-audio-stream FFmpeg measurement of supported local audio/video containers via `--request-json` and `--project-root`; valid noncompliant audio reports `within_tolerance=false`. See [meter request](SOUND_LOUDNESS_REQUESTS.md). |
| `sound-master-render` | Retain a verified mono/stereo two-pass master ZIP with required `--request-json` and `--project-root`. See [master request](SOUND_MASTER_REQUESTS.md). |
| `sound-qa-asr` | Local cached speech recognition against a reference script with required `--request-json` and `--project-root`. [Contract](SOUND_ASR_REQUESTS.md) |

Namespaced aliases (same handlers): `kino sound capabilities|plan-validate|voice-batch|mix-render|master-render|qa-loudness|qa-asr`.

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
| `composite-layers` | Spec-driven ordered image/video layer compositing with explicit alpha semantics, transforms, masks, named effect routes, blend modes, rotation/pivot, dry-run plans, and `layer_plan` v2 receipts |


### `composite-layers` spec

```bash
kino composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
kino composite-layers --spec layers.json -o out.mp4 --save-layer-plan layer-plan.json
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
      "alpha_mode": "straight",
      "opacity": 1.0,
      "transform": {"x": 120, "y": 80, "width": 640},
      "start": 0.25,
      "duration": 1.5
    },
    {"id": "title", "type": "image", "src": "title.png", "alpha_mode": "premultiplied", "opacity": 0.9, "position": {"x": 32, "y": 32}}
  ],
  "passes": [
    {"effect": "effect-noise", "target": "layer:plate", "args": {"mode": "film", "intensity": 0.10, "animated": false}},
    {"effect": "effect-noise", "target": "layer:plate.mask.edge", "args": {"mode": "color", "intensity": 0.05}}
  ],
  "output": {"format": "mp4"}
}
```

The compositor uses straight alpha internally. Layer `alpha_mode` defaults to `straight`; image/video inputs declared `premultiplied` are explicitly unpremultiplied before transforms and compositing. Per-layer opacity, fixed x/y positioning, `transform.width`, `transform.height`, `transform.scale`, `start`/`duration` timing windows, image/video/solid layers, and optional `mask`/`matte` alpha sources are supported. Top-level `passes` currently allowlist `effect-noise` and route it to `layer:<id>`, `layer:<id>.mask`, or `layer:<id>.mask.edge`; the receipt records normalized route decisions. Unknown effects, targets, arguments, and mask routes without a mask fail closed.

Allowlisted blend modes (`multiply`, `screen`, `overlay`, `darken`, `lighten`) work in full-canvas form and in a bounded positioned form. Non-`normal` blends support opacity and `start`/`duration` windows in two geometries: full-canvas at `{0,0}` without explicit sizing, or a positioned rectangle with both positive integer `width` and `height` and an integral nonnegative in-canvas position. RGB blending avoids color arithmetic on subsampled chroma planes. Scale, rotation/pivot, mask/matte, fractional positions and out-of-canvas rectangles remain deferred and fail closed. Video layers and video masks begin playback at their declared start. Rotation remains available for normal-blend layers (`rotation` within `[-360, 360]`, with `pivot`: `center`, `top_left`, `top_right`, `bottom_left`, or `bottom_right`; ordering is scale → rotate → routed layer effects → opacity → position). `anchor` remains a position alias. Output is video-only (`audio_policy: dropped_video_only`). Relative media paths must stay inside the spec directory. Rotation + mask remains deferred and fails closed.

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
kino workflow-validate --spec job.json
kino workflow-plan     --spec job.json [--save-plan plan.json] [--variant square]
kino workflow-render   --spec job.json [--resume receipt.json] [--save-receipt receipt.json] \
                            [--keep-intermediates] [--variant square] [--all-variants] [--save-receipt-dir receipts/]
kino workflow-inspect  --receipt receipt.json
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

## Dedicated Video Rescue

Rescue is review-first and local-only. `rescue-plan` never renders, `rescue-render` accepts
only safe IDs from that exact plan, and `rescue-inspect` reads either a plan or receipt. See
[RESCUE.md](RESCUE.md) for policy, package, cancellation, resume, and stable error contracts.

| Command | Description |
|---------|-------------|
| `rescue-plan` | Diagnose one local video and optionally save its immutable approval plan |
| `rescue-render` | Render approved safe repairs and a verified package; quarantine failures |
| `rescue-inspect` | Inspect a plan or receipt and re-check package integrity |

```bash
kino rescue-plan --source media/clip.mov --output-dir rescue-output --save-plan rescue-output/plan.json
kino --format json rescue-inspect --receipt rescue-output/plan.json
kino rescue-render --plan rescue-output/plan.json --approve rotation:metadata --save-receipt rescue-output/render-receipt.json
kino rescue-inspect --receipt rescue-output/render-receipt.json
```

| Flag | Command | Description |
|------|---------|-------------|
| `--source` | plan | Readable local video source (required) |
| `--output-dir` | plan | Confined output directory that cannot overwrite the source (required) |
| `--save-plan` | plan | Optional JSON plan path inside `output-dir` |
| `--policy` | plan | Policy ID; currently `local_content_preserving` |
| `--plan` | render | Reviewed rescue plan JSON (required) |
| `--approve` | render | Exact safe repair ID; repeat to select multiple IDs |
| `--save-receipt` | render | Optional render or cancellation receipt path |
| `--resume` | render | Compatible prior render receipt to resume |
| `--cancel-file` | render | Marker path checked between render stages |
| `--keep-intermediates` | render | Retain confined managed work files after success |
| `--receipt` | inspect | Rescue plan or render receipt JSON (required) |

Omitting `--approve` applies every safe repair in an already reviewed plan, never a
recommendation. There is no combined `rescue` command.

## Post-Rescue Planning

Each command accepts one positional UTF-8 JSON request artifact and emits a planning or
verification artifact. These commands do not render or perform network I/O.

| Command | Description |
|---------|-------------|
| `semantic-timeline REQUEST.json` | Build a source-backed semantic timeline |
| `semantic-query REQUEST.json` | Query local semantic spans |
| `timeline-edit-plan REQUEST.json` | Build a reviewable EDL and optional approved diff |
| `visual-transform-plan REQUEST.json` | Plan analysis, reframing, or stabilization |
| `restoration-plan REQUEST.json` | Plan or evaluate restorative work |
| `composition-plan REQUEST.json` | Build or verify a source-backed composition artifact |
| `creative-autopilot-plan REQUEST.json` | Coordinate available proven local planners |
| `remote-egress-plan REQUEST.json` | Plan explicit egress and fake remote receipts |

Use `--format json` for machine-readable output. Request files are capped at 4 MiB.

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
| `release-checkpoint` | Hard release quality gate, then thumbnail + storyboard for human review |

Quality JSON identifies each saturation and contrast metric, its unit, measured value, and whether the measurement was available. Technical and design checks use the same definitions. `video-quality-check --fail-on-warning` is a CI-style gate: it exits nonzero when `all_passed` is false. `release-checkpoint` is the CLI passthrough of the `video_release_checkpoint` MCP tool: it exits nonzero when the hard quality gate or validation fails, otherwise it writes a thumbnail and storyboard and marks `review_required: true` — inspect the artifacts before publishing.

## Image Analysis

| Command | Description |
|---------|-------------|
| `image-extract-colors` | Extract dominant colors from an image |
| `image-generate-palette` | Generate color harmony palette |
| `image-analyze-product` | Analyze product image (colors + AI description) |

## Hyperframes Commands

Relative render and requested still output paths resolve from the caller working
directory. A requested still output is atomically copied independently of mutable
snapshots and contains PNG bytes; changing its extension does not transcode it.
Without an explicit output, the existing snapshot path may be replaced by a later
snapshot. Missing still artifacts are errors.


| Command | Description |
|---------|-------------|
| `hyperframes-render` | Render a Hyperframes composition to video or PNG sequence; relative output resolves from caller cwd, false render results exit nonzero (`--composition`, `--resolution`, `--variables`, `--variables-file`; width/height must map to a preset) |
| `hyperframes-compositions` | List compositions in a Hyperframes project |
| `hyperframes-preview` | Launch Hyperframes preview studio |
| `hyperframes-still` | Render a single frame to the requested `-o` path, retaining it independently of mutable snapshots; accepts `--variables` and `--variables-file` runtime data |
| `hyperframes-snapshot` | Capture one or more rendered PNG snapshots; accepts `--variables` and `--variables-file` runtime data |
| `hyperframes-inspect` | Inspect rendered layout overflow and visual issues |
| `hyperframes-info` | Show Hyperframes project metadata |
| `hyperframes-catalog` | Browse catalog blocks and components |
| `hyperframes-capture` | Capture a website as editable Hyperframes components |
| `hyperframes-tts` | Generate local speech audio through Hyperframes |
| `hyperframes-transcribe` | Transcribe media or import transcript timing |
| `hyperframes-remove-background` | Cut a person (default) or a product/object (`--model birefnet-general`) out of a still or video. `--info` lists models. Guide: [PRODUCT_MATTE.md](PRODUCT_MATTE.md) |
| `hyperframes-doctor` | Run Hyperframes environment diagnostics |
| `hyperframes-benchmark` | Benchmark render settings (`--runs`) |
| `hyperframes-init` | Scaffold a new Hyperframes project (media bootstrap, Tailwind, and resolution flags) |
| `hyperframes-add-block` | Install a block from the Hyperframes catalog (`--no-clipboard`) |
| `hyperframes-validate` | Validate a Hyperframes project structure |
| `hyperframes-pipeline` | Render + post-process in one step |

Hyperframes project paths may be relative or absolute. Relative paths are resolved once against the caller's working directory before the command is executed.

## Revideo commands (development tip)

```bash
kino revideo-materialize DEST --job-json JSON [--scene-source PATH]
kino revideo-install PROJECT_DIR [--timeout SECONDS]
kino revideo-render PROJECT_DIR OUTPUT_PATH [--timeout SECONDS]
kino revideo-render-job OUTPUT_PATH --job-json JSON [--work-dir DIR] \
  [--scene-source PATH] [--install-timeout SECONDS] [--render-timeout SECONDS]
```

`--job-json` is a required inline JSON object with a one-megabyte limit. It is
never interpreted as a filename. Install and render are bounded; install may use
the npm registry, while render executes locally. `--format json` returns the
same flat success payloads as MCP. Render payloads retain the full receipt,
including output and exact on-disk job-file SHA-256 digests plus observed,
job-matched media metadata. The job file is capped at one MiB and even a
whitespace-only mutation during rendering invalidates its receipt binding.
Output formats are closed to `.mp4`, `.webm`, and `.mov`; the pinned exporter
uses MP4, WebM, and ProRes 4444 modes respectively and verifies that identity
before publication.
Custom scenes are trusted local
TypeScript and require quality and human review before release.

## Global Options

| Option | Description |
|--------|-------------|
| `--format text\|json` | Output format (default: text — rich tables & spinners) |
| `--version` | Show version and exit |
| `--mcp` | Run as MCP server (default when no command given) |
| `-v`, `--verbose` | Debug logs to stderr |
| `--log-file PATH` | Write structured DEBUG logs to PATH |

Planning/review JSON files and sound plans have a 1 MiB UTF-8 byte ceiling; post-rescue request files retain a 4 MiB ceiling. File admission requires a regular file and checks size before a bounded read. Inline JSON uses the same 1 MiB ceiling; malformed encoding or nesting deeper than 128 rejects with a redacted error before dispatch.
