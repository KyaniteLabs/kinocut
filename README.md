<p align="center">
  <a href="https://kyanitelabs.tech">
    <img src="assets/kinocut-hero.webp" alt="Kinocut - guardrailed video editing for AI agents" width="100%">
  </a>
</p>

<!-- mcp-name: io.github.KyaniteLabs/kinocut -->

<h1 align="center">Kinocut</h1>

<p align="center">
  <strong>Guardrailed video editing MCP server for AI agents.</strong><br>
  Local-first FFmpeg tools, Video Receipts, quality gates, Hyperframes, and Shorts/Reels repurposing —
  for Claude Code, Cursor, and any MCP client. Free, Apache-2.0. Formerly mcp-video.
</p>

<p align="center">
  <a href="https://pypi.org/project/kinocut/"><img src="https://img.shields.io/pypi/v/kinocut.svg" alt="PyPI"></a>
  <a href="https://kinocut.dev/"><img src="https://img.shields.io/badge/site-kinocut.dev-0A0A0A" alt="kinocut.dev"></a>
  <a href="https://git.kyanitelabs.tech/KyaniteLabs/kinocut/actions"><img src="https://img.shields.io/badge/Forgejo%20CI-actions-blue" alt="CI"></a>
  <img src="https://img.shields.io/badge/MCP-151%20tools-orange.svg" alt="151 MCP tools on development tip">
  <img src="https://img.shields.io/badge/CLI-130%20commands-orange.svg" alt="130 CLI commands on development tip">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
</p>

<p align="center">
  <a href="#see-it-work">Demo</a> &bull;
  <a href="#status-and-releases">Status</a> &bull;
  <a href="#whats-in-180-latest-release">1.8.0</a> &bull;
  <a href="#whats-next">Whats next</a> &bull;
  <a href="#installation">Install</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#mcp-tools">Tools</a> &bull;
  <a href="docs/TOOLS.md">Tool Reference</a> &bull;
  <a href="docs/RESCUE.md">Rescue</a> &bull;
  <a href="docs/AI_VIDEO_REVIEW_AND_SALVAGE.md">AI-video</a> &bull;
  <a href="#agent-skill">Agent Skill</a> &bull;
  <a href="https://kinocut.dev/">kinocut.dev</a> &bull;
  <a href="#what-is-kinocut">What is Kinocut?</a> &bull;
  <a href="#faq">FAQ</a> &bull;
  <a href="llms.txt">llms.txt</a>
</p>

---

## What is Kinocut?

**Kinocut** is a free, open-source **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server**, Python library, and **`kino` CLI** that gives AI agents a **guardrailed local video-editing surface**. It wraps **FFmpeg** (and optional Hyperframes / Whisper extras) with typed tools, preflight validation, **Video Receipt** provenance, and quality/release checkpoints so agent-produced media can be inspected before publish.

| | |
| --- | --- |
| **Also known as** | `kino` (CLI); formerly **mcp-video** / `mcp_video` |
| **Latest published release** | **[1.9.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.9.0)** (2026-07-15) |
| **Product site** | [kinocut.dev](https://kinocut.dev/) |
| **PyPI** | [`kinocut`](https://pypi.org/project/kinocut/) |
| **MCP Registry** | [`io.github.KyaniteLabs/kinocut`](https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest) |
| **Source** | [GitHub](https://github.com/KyaniteLabs/kinocut) · [Forgejo (canonical)](https://git.kyanitelabs.tech/KyaniteLabs/kinocut) |
| **License** | Apache-2.0 |
| **Runs on** | Your machine (macOS, Linux, Windows) — FFmpeg required on `PATH` |
| **Not** | A hosted cloud editor, credit-metered SaaS, or untyped FFmpeg shell wrapper |

**Best-fit searches:** video editing MCP server · AI agent video editing · FFmpeg MCP · Claude Code video tools · Cursor MCP video · Shorts/Reels automation · local AI video workflow · guardrailed agentic media.

Machine-readable brief for AI crawlers: [`llms.txt`](llms.txt) · site: [kinocut.dev/llms.txt](https://kinocut.dev/llms.txt).

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

**Primary job:** turn a local interview or podcast into **captioned vertical clips with a Video Receipt** agents can re-run and humans can approve.

**Three things people use it for**

- **Repurposing** — one recording into captioned Shorts, Reels, and TikTok packages with manifests and review artifacts.
- **Podcast & interview cuts** — find the strongest segment, normalize audio, add chapters, and export.
- **Agent-driven media in CI** — repeatable, reviewable edits from Claude Code, Cursor, Codex-style clients, or scripts.

**Paths:** [Install matrix](docs/INSTALL.md) · [Golden path](docs/GOLDEN_PATH.md) · [Prompts](docs/PROMPTS.md) · [Tutorial](docs/TUTORIAL_PODCAST_TO_SHORTS.md) · [Compare](docs/COMPARE.md) · [When to recommend](docs/RECOMMEND.md)

## Status and releases

| Surface | Version / tip | What it means |
| --- | --- | --- |
| **PyPI / npm / GitHub Release** | **[1.9.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.9.0)** (2026-07-15) | Latest **published** package. Install with `pip install -U kinocut`. |
| **This repository (`master`)** | **151 MCP tools / 130 CLI commands** | Development tip ahead of published 1.9.0 (release-artifact policy surfaces: review, publish gate, learning, cost, recipe, capabilities, benchmark). |
| **Next** | trusted execution kernel + sound program depth | See [Whats next](#whats-next). Not pinned to a specific package version yet. |

Install from PyPI for the stable package. Clone `master` only when you intentionally need post-tag tip work.

## What's in 1.9.0 (latest release)

Kinocut **1.9.0** is what you get from `pip install kinocut` today (**150 MCP tools / 129 CLI commands**). 1.9.0 adds public MCP/CLI/client surfaces for eight release-artifact policy engines (review package, publish gate, review decisions, learning report, cost ledger, recipe capture, capabilities, benchmark) on top of the 1.8.0 contract-first AI-video foundation:

- Everything from the **1.7.0** identity cutover (`kinocut` package, `kino` CLI, MCP Registry id, kinocut.dev)
- **Governed AI-video** — content-addressed ingest, unified preflight, temporal inspect, exact-asset verdict / acceptance, body-swap, lineage-bound salvage ([docs/AI_VIDEO_REVIEW_AND_SALVAGE.md](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md))
- **Optional C2PA** on path-based export (off by default; verify-after-sign)
- **Staged MCPB** package foundations (Desktop install experiments; **not** a fully self-contained published runtime)
- **Field safety** — loss-proof add-audio policies; authored ASS + dimension-aware subtitles
- **Hyperframes under MCP** — `hyperframes_init` no longer hangs without a TTY
- Compatibility: `mcp-video==1.6.2` installs `kinocut==1.8.0`; `mcp_video` imports, `MCP_VIDEO_*`, `~/.mcp-video`, `mcp-video://`, and legacy receipt keys remain supported on the 1.8.x line

Also still on the published line from earlier releases:

- Agent **workflow engine**, **video rescue**, **post-rescue planning**, **layered compositing**, expanded preflight guardrails

Full notes: [CHANGELOG.md](CHANGELOG.md) · [v1.8.0 release](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.8.0)

## Whats next

Post-1.8 product work (not a published package version):

### Already in 1.8.0

| Area | What landed on `master` | Start here |
| --- | --- | --- |
| **Governed AI-video** | Content-addressed `video_ingest`, unified `video_preflight`, temporal evidence (`video_inspect_temporal`), exact-asset `video_verdict` / `video_acceptance_eval`, audio-preserving `video_body_swap`, lineage-bound `video_salvage` | [docs/AI_VIDEO_REVIEW_AND_SALVAGE.md](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md) |
| **Project store / contracts** | Append-only private project storage, strict canonical records, protected-element checks, fail-soft optional visual providers | [docs/AI_VIDEO_CONTRACTS.md](docs/AI_VIDEO_CONTRACTS.md) · [docs/AI_VIDEO_INSPECTION.md](docs/AI_VIDEO_INSPECTION.md) |
| **Field safety** | Loss-proof add-audio duration policies; authored ASS + dimension-aware SRT/VTT subtitles | [CHANGELOG.md](CHANGELOG.md) 1.8.0 |
| **C2PA provenance** | Optional signing on path-based `export` / `Client.export()` via `c2patool` (off by default; only reports signed after verify) | [docs/C2PA_PROVENANCE.md](docs/C2PA_PROVENANCE.md) |
| **MCPB packaging** | Staged Desktop package + fail-closed native builder foundation; **not** a published self-contained runtime yet | [docs/MCPB.md](docs/MCPB.md) |
| **Repurpose skill** | Path-based [`skills/kinocut-repurpose`](skills/kinocut-repurpose/SKILL.md) + deterministic current-tools demo (marketing seed, not the final kernel-backed product) | [docs/REPURPOSE_SKILL.md](docs/REPURPOSE_SKILL.md) |
| **Hyperframes under MCP** | `hyperframes_init` no longer hangs without a TTY (non-interactive init + closed stdin) | [CHANGELOG.md](CHANGELOG.md) 1.8.0 |

### Upcoming pipeline (in progress)

Two coordinated programs remain after the published 1.8.0 release:

#### 1. AI-video + review/salvage finish

Contract-first media identity → inspection → human-gated verdict → bounded derivatives. Remaining work includes independent Wave-3 verification freeze, audio continuity, subtitle/graphics QA depth, asset intelligence, editorial planning, learning reports, and whole-program acceptance. Sequencing: [wishlist parallel execution](docs/plans/2026-07-12-wishlist-parallel-execution.md) · current status: [post-1.8 program status](docs/status/2026-07-14-post-1.8-program-status.md).

#### 2. `kinocut_sound` (Sonic World) — full-episode audio production

Standalone-capable sound package **inside this repo** (`kinocut_sound/`): plan/timeline/routing/consent → voice → post/spatial → ambience/world → mix/stems → QA/metadata → thin public adapters → host joins → dual-class benchmark → STOP.

| Slice | Focus | Status (as of 2026-07-14) |
| --- | --- | --- |
| S1–S4 | Contracts, authorization, registry/policy, script/episode planning | Implemented foundation leaves |
| S5 / S7 / S8 | Base voice, post/spatial chain, ambience/world | Integrated leaves on master |
| S6 / S10 | Consent-gated clone/blend; voice consistency | Integrated leaves on master |
| S9 / S11 | Mix assembly/stems; QA + metadata | Integrated leaves on master |
| S12 | Thin public discovery / Python adapters | Integrated (capability discovery surface) |
| **S13** | Kinocut/host joins (D41/D42 production bindings) | **Blocked** — external owner receipts incomplete |
| **S14** | Dual-class benchmark (Apple silicon + x86 Linux) | **Partial** — x86 available; Apple class `external_host_unavailable` |
| **S15** | Adversarial acceptance + release STOP | **STOP** — no ship without dual-class S14, S13 receipts, independent review, human authorization |

Authoritative receipts: [sound program handoff](docs/status/2026-07-13-sound-program-strategic-handoff.md) · [S13–S15 gate](docs/status/2026-07-14-sound-s13-s15-gate-receipt.md) · [sound plan index](docs/superpowers/plans/2026-07-12-kinocut-sound-plan-index.md).

#### 3. Trusted execution kernel (post-program, gated)

The approved [trusted execution layer plan](docs/plans/2026-07-09-kinocut-trusted-execution-layer.md) still defines the durable product path after the current program: durable edit projects, async render/resume wrapping `video_workflow_*`, receipt lineage, then kernel-backed repurposing as the “made just by prompting” moment. The protected-timeline kernel **does not start** merely because sound/AI-video leaves land — it needs the named upstream contract and an explicit human gate.

Product checklist: [ROADMAP.md](ROADMAP.md).

## Agent Workflow Engine

Agents can **plan, validate, render, recover, and prove** a multi-step local video job from
a single JSON job-spec — through MCP (`video_workflow_*`), the CLI (`workflow-*`), or the
Python client (`Client.workflow_*`) — with receipts strong enough for another agent or a
human to trust before *and* after a render. Ops are a small allowlist
(`probe | trim | resize | convert | merge | add_text | composite_layers`) mapped 1:1 to the same vetted engine
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
  "versions": { "mcp_video": "1.8.0", "ffmpeg": "8.1" },
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

## Governed AI-video review

On the **development tip**, Kinocut adds a contract-first path for agent-edited media that must stay attributable and reviewable:

1. **Ingest** the source into a private content-addressed project (`video_ingest` / `video-ingest`)
2. **Preflight + temporal inspection** on the stored asset (`video_preflight`, `video_inspect_temporal`)
3. **Verdict + acceptance** with exact human evidence (`video_verdict`, `video_acceptance_eval`)
4. **Bounded derivatives only** — audio-preserving body swap or allowlisted salvage recipes (`video_body_swap`, `video_salvage`), each with lineage and a fresh non-approved review slot

There is no force/bypass flag. Analyzer output alone cannot approve. Stale, aliased, or protected inputs fail closed. Operating guide: [docs/AI_VIDEO_REVIEW_AND_SALVAGE.md](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md). These surfaces ship in published **1.8.0** — see [Status and releases](#status-and-releases).

## Dedicated Video Rescue

For "fix this clip" requests where the story and timeline must remain unchanged, use the
review-first rescue pipeline. Plan and inspect the diagnosis, approve only safe repair IDs,
render, then inspect the verified package. The source stays immutable; master and universal
sharing copy are always verified; optional captions remain sidecars. See
[docs/RESCUE.md](docs/RESCUE.md) for CLI, MCP, Python, cancellation, resume, and stable errors.

## Layered Compositing

`composite-layers` / `video_composite_layers` adds a spec-driven ordered layer stack for agents that need more than two-shot overlay primitives. It supports image, video, and solid layers; normal alpha compositing; per-layer opacity; x/y placement; transform sizing; timing windows; and mask/matte alpha sources — plus allowlisted **full-canvas and positioned blend modes** (`multiply`, `screen`, `overlay`, `darken`, `lighten`) and **rotation** with a new `pivot` reference point. Dry-run plans and deterministic `layer_plan` v2 receipts capture source, filtergraph, and output hashes.

```bash
kino composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
kino composite-layers --spec layers.json -o out.mp4 --save-layer-plan layer-plan.json
```

Use `composite-layers` when an agent needs a planned stack of overlays, mattes, lower thirds, blurback plates, or platform variants that should be reviewed before rendering. A non-`normal` blend layer may remain full-canvas, or it may use the positioned allowlist: explicit `width` **and** `height`, an integral nonnegative in-canvas `position`, full opacity, and no scale, rotation/pivot, mask/matte, or timing window. Positioned blend crops the running base to the rectangle, blends the same-size layer, then overlays the result back at that position. Other blend geometry fails closed with `unsupported_blend_geometry`; output is video-only.

## Public Discovery

Kinocut is built to be **findable and citable** by both search engines and AI answer engines:

- Canonical product URL: **https://kinocut.dev/**
- GitHub README + [`llms.txt`](llms.txt) with entity facts, install commands, and safety rules
- Official MCP Registry record under `io.github.KyaniteLabs/kinocut`
- FAQ answers in this README and [docs/faq.md](docs/faq.md) (answer-first, versioned claims)

### Kinocut vs raw FFmpeg (and vs cloud editors)

| | Kinocut | Raw FFmpeg in agent shell | Typical cloud editor API |
| --- | --- | --- | --- |
| Interface | Typed MCP / Python / CLI | Free-form flags | Hosted HTTP API |
| Preflight | Guardrails before render | Agent invents flags | Vendor-specific |
| Provenance | Video Receipts + hashes | Ad-hoc logs | Vendor dashboard |
| Media location | Local-first | Local | Upload required |
| Core cost | Free (Apache-2.0) | Free | Often metered |

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

For Claude Desktop-style MCPB installs, Kinocut includes a staged local package at
`mcpb/` and a local build script:

```bash
python3 scripts/build-mcpb.py
```

This package is honest about its runtime: it launches an existing Python environment with
Kinocut installed and still requires local FFmpeg. Native self-contained bundles remain blocked
pending FFmpeg provenance, licensing, and clean-machine gates. See [docs/MCPB.md](docs/MCPB.md).

Optional **C2PA** signing for final MP4 exports is available on the development tip when
`c2patool` and a manifest/signer are configured. Signing is off by default and only reports
`signed` after a verification read succeeds. See [docs/C2PA_PROVENANCE.md](docs/C2PA_PROVENANCE.md).

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

`mcp-video==1.6.2` is a metadata-only compatibility installer for `kinocut==1.8.0`. The `mcp_video` import, `mcp-video` command, `MCP_VIDEO_*` environment variables, `~/.mcp-video` data directory, `mcp-video://` resource URIs, and existing receipt keys remain supported on the 1.8.x line. New integrations should use `kinocut`, `from kinocut import Client`, and the `kino` command.

## En español

Kinocut es un servidor MCP de edición de video para agentes de IA. La última versión publicada es **1.9.0** (`pip install kinocut`) con **150 herramientas MCP** y **129 comandos CLI** sobre FFmpeg para recortar, unir, subtitular, mezclar audio, aplicar efectos y reutilizar contenido (Shorts, Reels, TikTok), más un motor de flujos de trabajo (`workflow`) con recibos verificables, rescate de video, revisión AI-video gobernada y barreras de seguridad antes de renderizar.

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

### Golden path (60 seconds)

Prove the install works before wiring an agent host:

```bash
pip install -e .          # or: pip install kinocut
kino doctor               # required checks must pass
python scripts/golden_path.py
```

Success criteria and failure recovery: [`docs/GOLDEN_PATH.md`](docs/GOLDEN_PATH.md).  
Shareable pack (receipt + quality + media): `python scripts/generate_golden_pack.py` → [`demo/golden-pack/`](demo/golden-pack/).

### Try the receipt-backed proof first

From a clone of this repo, run the smallest confidence workflow before wiring an agent host:

```bash
uv run --no-project --with kinocut python workflows/05-confidence-baseline/workflow.py
uv run --no-project --with kinocut python workflows/benchmarks/run_confidence_benchmark.py
```

The workflow generates a tiny source clip, creates a checked vertical video, runs quality/release checkpoint steps, and writes `workflows/05-confidence-baseline/output/video_receipt.json`.

Proof notes live in [`docs/proofs/`](docs/proofs/). Public marketing claims (version, tool counts, URLs) live in [`docs/public_claims.json`](docs/public_claims.json) and are CI-guarded.

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

For path-based short-form packages from **current tools only** (no invented commands, no external publish), see [`skills/kinocut-repurpose/SKILL.md`](skills/kinocut-repurpose/SKILL.md). That skill is an explicit marketing seed; the durable kernel-backed repurposing product is still on the trusted-execution roadmap.

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
| Video rescue | "Diagnose this damaged clip, propose only safe repairs, render an approved package, and verify the receipt." |
| Governed review (dev tip) | "Ingest this export into a project, run preflight and temporal inspection, write a verdict, and salvage only the broken region." |

## MCP Tools

Published **1.9.0** registers **150 MCP tools** and **129 CLI commands** (including governed AI-video surfaces). The table summarizes core categories — `search_tools` discovers the exact operation without loading every description.

| Category | Count | Highlights |
| --- | ---: | --- |
| Core video editing | 32 | trim, merge, resize, crop, rotate, convert, overlays, subtitles, export, cleanup, templates, merge-compatibility guardrails |
| Project-backed inspection | 3 | content-addressed ingest, unified preflight, temporal evidence packages |
| Governed AI-video | 4 | exact-asset verdicts, acceptance evaluation, audio-preserving body swaps, lineage-bound salvage |
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
- For governed AI-video derivatives (dev tip), require stored identities, active human decision evidence, and a fresh review slot after every salvage or body-swap — never raw FFmpeg workarounds labeled as governed.

## FAQ

### What is Kinocut?

Kinocut is a free, open-source MCP server, Python library, and `kino` CLI for AI-agent video editing. It wraps FFmpeg (and optional Hyperframes/Whisper extras) with preflight guardrails, Video Receipts, and quality checkpoints. It was formerly named **mcp-video**.

### How do I install it?

```bash
brew install ffmpeg   # or apt install ffmpeg
pip install kinocut
kino doctor
claude mcp add kinocut -- uvx --from kinocut kino
```

### Is it free and local-first?

Yes. Apache-2.0, runs on your machine, no Kinocut account or API key required for the core surface, and media is not uploaded to a Kinocut cloud.

### Which agents work with it?

Any MCP-compatible client that can run a local stdio server (Claude Code, Cursor, Windsurf, Cline, and similar). You can also use the Python client or CLI without an agent.

### How many tools are there?

Published **1.9.0** documents **150 MCP tools / 129 CLI commands**. Historical **1.7.0** cutover was **135 / 114**.

### Was it called mcp-video?

Yes. `mcp-video==1.6.2` installs `kinocut==1.8.0`. Compatibility imports, CLI name, env vars, data dir, resource URIs, and receipt keys remain supported on the 1.8.x line.

More answers: [docs/faq.md](docs/faq.md) · on-site FAQ: [kinocut.dev/#faq](https://kinocut.dev/#faq)

## Documentation

- [Documentation map](docs/README.md)
- [Product site](https://kinocut.dev/)
- [Tool reference](docs/TOOLS.md)
- [Python client reference](docs/PYTHON_CLIENT.md)
- [CLI reference](docs/CLI_REFERENCE.md)
- [Agent workflow engine](docs/WORKFLOWS.md)
- [Video receipts](docs/VIDEO_RECEIPT.md)
- [Video rescue](docs/RESCUE.md)
- [Post-rescue planning](docs/POST_RESCUE_FEATURES.md)
- [AI-video review and salvage](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md)
- [AI-video contracts](docs/AI_VIDEO_CONTRACTS.md)
- [AI-video inspection](docs/AI_VIDEO_INSPECTION.md)
- [C2PA provenance](docs/C2PA_PROVENANCE.md)
- [MCPB packaging](docs/MCPB.md)
- [Product roadmap](ROADMAP.md)
- [Trusted execution layer plan](docs/plans/2026-07-09-kinocut-trusted-execution-layer.md)
- [Wishlist / 1.8 program parallel plan](docs/plans/2026-07-12-wishlist-parallel-execution.md)
- [Sound program status](docs/status/2026-07-13-sound-program-strategic-handoff.md)
- [AI agent discovery guide](docs/AI_AGENT_DISCOVERY.md)
- [FAQ](docs/faq.md)
- [Golden path (first-run proof)](docs/GOLDEN_PATH.md)
- [Public claims (version / counts)](docs/public_claims.json)
- [Golden demo pack](demo/golden-pack/README.md)
- [Changelog](CHANGELOG.md)
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
