<p align="center">
  <a href="https://kyanitelabs.tech">
    <img src="assets/mcp-video-hero.webp" alt="Kinocut - guardrailed video editing for AI agents" width="100%">
  </a>
</p>

<!-- mcp-name: io.github.KyaniteLabs/kinocut -->

<h1 align="center">Kinocut</h1>

<p align="center">
  <strong>Guardrailed video editing MCP server for AI agents.</strong><br>
  Structured tools for FFmpeg video editing, cinematic prompt planning, media analysis, subtitles, audio, effects, Hyperframes video creation, local repurposing packages, and preflight validation that helps prevent silent bad media output.
</p>

<p align="center">
  <a href="https://pypi.org/project/kinocut/"><img src="https://img.shields.io/pypi/v/kinocut.svg" alt="PyPI"></a>
  <a href="https://git.kyanitelabs.tech/KyaniteLabs/kinocut/actions"><img src="https://img.shields.io/badge/Forgejo%20CI-actions-blue" alt="CI"></a>
  <img src="https://img.shields.io/badge/MCP-135%20tools-orange.svg" alt="135 MCP tools">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <a href="https://registry.modelcontextprotocol.io/servers/io.github.KyaniteLabs/kinocut"><img src="https://img.shields.io/badge/MCP-Registry-blue.svg" alt="MCP Registry"></a>
</p>

<p align="center">
  <a href="#see-it-work">Demo</a> &bull;
  <a href="#install">Install</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#what-agents-can-do">Agent Workflows</a> &bull;
  <a href="#tool-surface">Tools</a> &bull;
  <a href="docs/TOOLS.md">Tool Reference</a> &bull;
  <a href="docs/RESCUE.md">Video Rescue</a> &bull;
  <a href="docs/AI_AGENT_DISCOVERY.md">AI Discovery</a> &bull;
  <a href="#agent-skill">Agent Skill</a> &bull;
  <a href="llms.txt">llms.txt</a> &bull;
  <a href="https://registry.modelcontextprotocol.io/servers/io.github.KyaniteLabs/kinocut">MCP Registry</a>
</p>

---

## See It Work

Tell the agent what you want in plain language:

> "Trim this interview to the strongest 45 seconds, add burned captions, make it vertical, and quality-check it before export."

Kinocut turns that into typed, guardrailed tool calls - no FFmpeg flags to guess, no silently broken exports:

```python
from kinocut import Client
video = Client()

clip = video.trim("interview.mp4", start="00:02:15", duration="00:00:45")
video.ai_transcribe(clip.output_path, output_srt="captions.srt")
captioned = video.subtitles(clip.output_path, subtitle_file="captions.srt")
short = video.resize(captioned.output_path, aspect_ratio="9:16")
video.release_checkpoint(short.output_path)  # thumbnail + quality gate before you publish
```

**Three things people use it for**

- **Repurposing** — one recording into captioned Shorts, Reels, and TikTok packages with manifests and review artifacts.
- **Podcast & interview cuts** — find the strongest segment, normalize audio, add chapters, and export.
- **Agent-driven media in CI** — repeatable, reviewable edits from Claude Code, Cursor, Codex-style clients, or scripts.

## Agent Workflow Engine

Agents can **plan, validate, render, recover, and prove** a multi-step local video job from
a single JSON job-spec — through MCP (`video_workflow_*`), the CLI (`workflow-*`), or the
Python client (`Client.workflow_*`) — with receipts strong enough for another agent or a
human to trust before *and* after a render. Ops are a small allowlist
(`probe | trim | resize | convert | merge | add_text`) mapped 1:1 to the same vetted engine
functions the individual tools use; media references are symbolic and workspace-confined;
everything fails closed.

```json
{
  "schema_version": 1,
  "name": "captioned-vertical-short",
  "sources": { "hero": { "path": "input/hero.mp4" } },
  "steps": [
    { "id": "trim-hero", "op": "trim", "inputs": { "src": "@sources.hero" },
      "params": { "start": 0, "duration": 6 }, "output": "@work/hero_trim.mp4" },
    { "id": "vertical", "op": "resize", "inputs": { "src": "@work/hero_trim.mp4" },
      "params": { "width": 1080, "height": 1920 }, "output": "@work/hero_vertical.mp4" },
    { "id": "caption", "op": "add_text", "inputs": { "src": "@work/hero_vertical.mp4" },
      "params": { "text": "Watch this", "position": "bottom-center" }, "output": "@outputs.master" }
  ],
  "outputs": { "master": { "path": "output/final.mp4" } }
}
```

```bash
kino workflow-validate --spec job.json    # cheap structural gate, no render
kino workflow-plan     --spec job.json --save-plan plan.json     # dry-run op graph + hashes
kino workflow-render   --spec job.json --save-receipt receipt.json   # execute + provenance receipt
kino workflow-inspect  --receipt receipt.json    # read-only integrity re-check
```

The render receipt records per-step input/output hashes, a resume cursor, and a cleanup
manifest, all with workspace-relative paths:

```json
{
  "receipt_kind": "workflow",
  "versions": { "mcp_video": "1.7.0", "ffmpeg": "8.1" },
  "spec_hash": "sha256:be2f3a9b...",
  "steps": [
    { "id": "trim-hero", "op": "trim", "status": "completed",
      "input_hashes": { "src": "sha256:3b976d49..." },
      "output": "work/be2f3a9b-2effedb3/mcp_video_hero_trim.mp4", "output_hash": "sha256:00727499..." },
    { "id": "caption", "op": "add_text", "status": "completed",
      "output": "output/final.mp4", "output_hash": "sha256:8633ad2a..." }
  ],
  "cleanup_manifest": { "cleaned": true, "policy": "clean-on-success" },
  "resume_cursor": { "last_completed_step": "caption", "next_step": null },
  "status": "completed",
  "render_determinism_scope": "spec/input/output hashes are deterministic; rendered bytes may vary across FFmpeg builds"
}
```

`--all-variants` emits N distinct outputs from one declaration, and `--resume` continues a
job that failed with its intermediates kept (fail-closed on a changed spec). Full schema,
`@ref` grammar, variants, resume, and cleanup are in
[docs/WORKFLOWS.md](docs/WORKFLOWS.md); a runnable spec is in
[examples/workflows/](examples/workflows/captioned-vertical-short/).

## Dedicated Video Rescue

For "fix this clip" requests where the story and timeline must remain unchanged, use the
review-first rescue pipeline. Plan and inspect the diagnosis, approve only safe repair IDs,
render, then inspect the verified package. The source stays immutable; master and universal
sharing copy are always verified; optional captions remain sidecars. See
[docs/RESCUE.md](docs/RESCUE.md) for CLI, MCP, Python, cancellation, resume, and stable errors.

## Layered Compositing

`composite-layers` / `video_composite_layers` adds a spec-driven ordered layer stack for agents that need more than two-shot overlay primitives. It supports image, video, and solid layers; normal alpha compositing; per-layer opacity; x/y placement; transform sizing; timing windows; and mask/matte alpha sources — plus **full-canvas blend modes** (`multiply`, `screen`, `overlay`, `darken`, `lighten`) and **rotation** with a new `pivot` reference point. Dry-run plans and deterministic `layer_plan` v2 receipts capture source, filtergraph, and output hashes.

```bash
kino composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
kino composite-layers --spec layers.json -o out.mp4 --save-layer-plan layer-plan.json
```

Use `composite-layers` when an agent needs a planned stack of overlays, mattes, lower thirds, blurback plates, or platform variants that should be reviewed before rendering. A non-`normal` blend layer must be full-canvas (position `{0,0}`, full opacity, no scale/mask/timing) or it fails closed; output is video-only. Positioned/scaled/masked/timed blend, rotation + mask, and per-layer effect routing are tracked as later phases so this surface stays deterministic and preflightable.

## Public Discovery

**Kinocut** is a free, open-source **Model Context Protocol (MCP) server**, Python library, and CLI that gives AI agents a real video-editing surface. It wraps FFmpeg, PUSHING CREATION-style planning, media analysis, quality checks, subtitles, audio generation, effects, Hyperframes rendering, local repurposing packages, and guardrails for risky edit parameters behind structured tool schemas.

Best-fit searches:

- video editing MCP server
- AI agent video editing
- FFmpeg MCP tools
- Claude Code video editing
- Cursor MCP video tools
- Python video editing library
- subtitle automation
- reels and shorts automation
- agentic media pipeline
- local AI video workflow
- Hyperframes video creation
- YouTube Shorts repurposing

## Why It Exists

AI agents can write FFmpeg commands, but they should not have to guess flags, parse brittle stderr, or silently publish broken media. Kinocut gives agents typed operations, inspectable tool metadata, structured results, preflight guardrails, and quality checkpoints so a video workflow can be automated and reviewed without turning into shell-command roulette.

Use it when you want an AI assistant to:

- trim, merge, resize, crop, rotate, transcode, or export video;
- add text, subtitles, watermarks, overlays, filters, fades, effects, and transitions;
- extract audio, normalize audio, synthesize audio, add generated audio, or create waveforms;
- detect scenes, make thumbnails, generate storyboards, compare quality, and create release checkpoints;
- scaffold cinematic projects, read STYLE_/NEG_ blocks, parse storyboard tables, and expand shot prompts;
- create new Hyperframes projects, inspect rendered layouts, capture websites, generate local speech, remove backgrounds, and post-process the result with FFmpeg tools;
- repurpose one source video into vertical, horizontal, and square local delivery packages with manifests and review artifacts;
- drive repeatable media workflows from Claude Code, Cursor, Codex-style clients, scripts, or CI.

## Installation

Prerequisite: [FFmpeg](https://ffmpeg.org/) must be installed and available on `PATH`.

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

Run without a global install:

```bash
uvx --from kinocut kino doctor
```

Or install with pip:

```bash
pip install kinocut
kino doctor
```

Hyperframes tools additionally need Node.js 22+ and a resolvable Hyperframes CLI. Install/pin Hyperframes in the active Node package layout, add `hyperframes` to `PATH`, or set `MCP_VIDEO_HYPERFRAMES_COMMAND`.

### Which extra do I need?

The core install covers all FFmpeg editing tools. Optional features ship as extras — install only what you use:

| You want | Install | Approx. extra size |
|---|---|---|
| Speech-to-text subtitles (Whisper) | `pip install "kinocut[transcribe]"` | ~1 GB (torch) |
| Image analysis (colors, layout, contrast) | `pip install "kinocut[image]"` | ~50 MB |
| Vocal/instrument stem separation | `pip install "kinocut[stems]"` | ~2 GB (torch + demucs) |
| AI upscaling | `pip install "kinocut[upscale]"` | ~2 GB (Python ≤3.12) |
| Procedural audio/music tools | `pip install "kinocut[audio]"` | ~30 MB (numpy) |
| Everything AI | `pip install "kinocut[ai]"` | several GB |

Mix freely, e.g. `pip install "kinocut[transcribe,image]"`. Run `kino doctor` afterward — it reports exactly which features are available and what is missing.

### Upgrading from mcp-video

Kinocut preserves the original surface during the rename window. Existing installs can upgrade without changing code:

```bash
pip install --upgrade mcp-video
mcp-video doctor
```

`mcp-video==1.6.1` is a metadata-only compatibility installer for `kinocut==1.7.0`. The `mcp_video` import, `mcp-video` command, `MCP_VIDEO_*` environment variables, `~/.mcp-video` data directory, `mcp-video://` resource URIs, and existing receipt keys remain supported through at least Kinocut 1.8.x. New integrations should use `kinocut`, `from kinocut import Client`, and the `kino` command.

## En español

Kinocut es un servidor MCP de edición de video para agentes de IA: 135 herramientas estructuradas sobre FFmpeg para recortar, unir, subtitular, mezclar audio, aplicar efectos y reutilizar contenido (Shorts, Reels, TikTok), más un motor de flujos de trabajo (`workflow`) que planifica, valida, renderiza, reanuda y prueba trabajos de varios pasos con recibos verificables, y barreras de seguridad que detectan parámetros riesgosos antes de renderizar.

Requisito: [FFmpeg](https://ffmpeg.org/) instalado y disponible en el `PATH`.

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Instalación y diagnóstico
pip install kinocut
kino doctor
```

Para Claude Code:

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

`kino doctor` informa qué funciones están disponibles y qué falta instalar. La documentación completa está en inglés; los mensajes de error principales son bilingües.

## Quick Start

### Try the receipt-backed proof first

From a clone of this repo, run the smallest confidence workflow before wiring an agent host:

```bash
uv run --no-project --with kinocut python workflows/05-confidence-baseline/workflow.py
uv run --no-project --with kinocut python workflows/benchmarks/run_confidence_benchmark.py
```

The workflow generates a tiny source clip, creates a checked vertical video, runs quality/release checkpoint steps, and writes `workflows/05-confidence-baseline/output/video_receipt.json`.

Proof notes live in [`docs/proofs/`](docs/proofs/).

### Claude Code

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

### Claude Desktop

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

### Cursor

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

Then ask your agent:

> Trim this interview into a 45-second vertical clip, add burned captions, normalize the audio, make a thumbnail, and create a release checkpoint before export.

## Agent Skill

Kinocut includes a public agent skill at [`skills/kinocut/SKILL.md`](skills/kinocut/SKILL.md). Use `$kinocut` in compatible agent hosts when you want the agent to choose between the MCP server, CLI, and Python client while preserving the inspect, edit, verify, and human-review workflow.

## Python Client

```python
from kinocut import Client

editor = Client()

clip = editor.trim("interview.mp4", start="00:02:15", duration="00:00:45")
caption_file = "captions.srt"
editor.ai_transcribe(clip.output_path, output_srt=caption_file)
captioned = editor.subtitles(clip.output_path, subtitle_file=caption_file)
vertical = editor.resize(captioned.output_path, aspect_ratio="9:16")
checkpoint = editor.release_checkpoint(vertical.output_path)

print(checkpoint["thumbnail"])
print(checkpoint["storyboard"])
```

## CLI

```bash
kino info interview.mp4
kino trim interview.mp4 -s 00:02:15 -d 45
kino video-ai-transcribe clip.mp4 --output captions.srt
kino subtitles clip.mp4 captions.srt
kino resize clip.mp4 --aspect-ratio 9:16
kino video-quality-check clip.mp4
kino repurpose clip.mp4 --platforms youtube-shorts instagram-reel tiktok
```

## What Agents Can Do

| Workflow | Example prompt |
| --- | --- |
| Social clips | "Turn this landscape recording into a captioned TikTok and YouTube Short." |
| Podcast production | "Find the strongest segment, trim it, normalize audio, add chapters, and export." |
| Product demos | "Create a short launch video from screenshots, title cards, and voiceover." |
| Cinematic planning | "Create a style pack and storyboard, then render shot prompts for generation." |
| Quality review | "Compare these two exports, make thumbnails, and flag visual or audio problems." |
| Batch automation | "Convert this folder of clips to web-ready MP4 with consistent loudness." |
| Code-created video | "Scaffold a Hyperframes composition, inspect it, render it, then add subtitles and a watermark." |
| Local repurposing | "Turn this master clip into Shorts, Reels, TikTok, and YouTube assets with thumbnails and a manifest." |

## MCP Tools

kino currently registers **135 MCP tools**. The table below summarizes the documented core categories; `search_tools` lets agents discover the exact operation they need without loading every tool description into context.

| Category | Count | Highlights |
| --- | ---: | --- |
| Core video editing | 32 | trim, merge, resize, crop, rotate, convert, overlays, subtitles, export, cleanup, templates, merge-compatibility guardrails |
| Agent workflow engine | 4 | validate, plan, render, resume, inspect multi-step jobs with provenance receipts |
| Dedicated rescue | 3 | diagnose, approve, render, verify, quarantine, and resume local content-preserving repairs |
| Post-rescue planning | 8 | semantic timelines/query, EDLs, visual transforms, restoration, composition, autopilot, explicit egress |
| Cinematic creation | 4 | project scaffold, style-pack parsing, storyboard parsing, shot prompt expansion |
| AI-assisted media | 11 | transcription, scene detection, upscaling, stem separation, silence removal, color grading |
| Hyperframes | 18 | init, preview, render, snapshots, inspect, catalog, website capture, local TTS, transcription, background removal, diagnostics, benchmark, post-process |
| Repurposing | 2 | dry-run manifests, platform-ready variants, thumbnails, storyboards, release checkpoints |
| Procedural audio | 7 | synthesize, compose, presets, effects, sequences, generated audio, spatial audio, mix-parameter guardrails |
| Visual effects | 8 | vignette, glow, noise, scanlines, chromatic aberration, luma key, mask, shape mask, bounded filter parameters |
| Transitions | 3 | glitch, morph, pixelate |
| Layout and motion | 6 | grid, picture-in-picture, split-screen, animated text, counters, progress bars, auto-chapters, layout mismatch warnings |
| Analysis | 8 | scene detection, thumbnail, preview, storyboard, quality compare, metadata, waveform, release checkpoint |
| Image analysis | 3 | extract colors, generate palettes, analyze product images |
| Discovery | 1 | `search_tools` |

```python
from kinocut import Client

editor = Client()
matches = editor.search_tools("subtitle")
print(matches["tools"])
```

Full reference: [docs/TOOLS.md](docs/TOOLS.md)

## Agent-Safe Workflow

For autonomous agents, the intended path is inspect, edit, verify, then ask a human to review release artifacts:

```python
from kinocut import Client

client = Client()

print(client.inspect("trim"))

result = client.pipeline(
    [
        {"op": "trim", "input": "source.mp4", "start": "00:01:00", "duration": "00:00:45"},
        {"op": "add_text", "text": "Launch clip", "position": "top-center"},
        {"op": "normalize_audio"},
        {"op": "resize", "aspect_ratio": "9:16"},
        {"op": "export", "quality": "high"},
        {"op": "release_checkpoint"},
    ],
    output_path="final-short.mp4",
)
```

Safety contract:

- Media-producing calls return structured results with output paths.
- High-risk edit paths now run preflight guardrails before FFmpeg execution: filter bounds, merge compatibility, audio mix volume/timing, overlay/watermark/chroma opacity and similarity, animated text timing/overflow, and grid/split-screen mismatch warnings.
- Analysis and discovery calls return structured JSON reports.
- Tool discovery is available through `search_tools()` and `Client.inspect()`.
- Unexpected keyword errors are converted into actionable `MCPVideoError` guidance.
- Do not publish agent-generated video without `video_quality_check`, `video_release_checkpoint`, and human visual/audio inspection.

## Documentation

- [Tool reference](docs/TOOLS.md)
- [Python client reference](docs/PYTHON_CLIENT.md)
- [Post-rescue planning](docs/POST_RESCUE_FEATURES.md)
- [CLI reference](docs/CLI_REFERENCE.md)
- [AI agent discovery guide](docs/AI_AGENT_DISCOVERY.md)
- [FAQ](docs/faq.md)
- [llms.txt](llms.txt)

## Testing

Development verification lives in [docs/TESTING.md](docs/TESTING.md). Keep public-surface, media workflow, and security checks current when changing tool behavior.

## Development

```bash
git clone https://git.kyanitelabs.tech/KyaniteLabs/kinocut.git
cd kinocut
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v -m "not slow and not hyperframes"
```

## Community

- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Governance](GOVERNANCE.md)
- [Maintainers](MAINTAINERS.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [Forgejo issues](https://git.kyanitelabs.tech/KyaniteLabs/kinocut/issues)

## License

Apache 2.0. See [LICENSE](LICENSE).

Built with [FFmpeg](https://ffmpeg.org/), [Hyperframes](https://hyperframes.io/), and the [Model Context Protocol](https://modelcontextprotocol.io/).

---

## Part of KyaniteLabs

More from [KyaniteLabs](https://kyanitelabs.tech). Related projects:

- **[Epoch](https://github.com/KyaniteLabs/Epoch)** — time-estimation MCP server (PERT) for AI agents
- **[DialectOS](https://github.com/KyaniteLabs/DialectOS)** — Spanish dialect localization MCP server & CLI
- **[checkyourself](https://github.com/KyaniteLabs/checkyourself)** — local-first production-readiness checks for AI-built code

→ More at **[kyanitelabs.tech](https://kyanitelabs.tech)**

---

If Kinocut is useful to you, **[star or watch it](https://git.kyanitelabs.tech/KyaniteLabs/kinocut)** — it helps other agent builders find it.

Built by **[Simon Gonzalez De Cruz](https://github.com/simongonzalezdc)** — available for Forward-Deployed / Applied-AI engineering and contract work via the public profile links above.
