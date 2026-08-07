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
  <img src="https://img.shields.io/badge/MCP-194%20tools-orange.svg" alt="194 MCP tools on development tip">
  <img src="https://img.shields.io/badge/CLI-165%20commands-orange.svg" alt="165 CLI commands on development tip">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
</p>

<p align="center">
  <a href="#installation">Install</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#whats-in-1130">1.13.0</a> ·
  <a href="#agent-skill">Agent skill</a> ·
  <a href="#mcp-tools">Tools</a> ·
  <a href="docs/TOOLS.md">Tool reference</a> ·
  <a href="https://kinocut.dev/">kinocut.dev</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="llms.txt">llms.txt</a>
</p>

---

## What is Kinocut?

**TL;DR:** Kinocut is a free, local-first **video editing MCP server** (plus Python client and `kino` CLI) so AI agents can trim, caption, repurpose, and quality-gate media with typed tools and **Video Receipts** — not invented FFmpeg flags.

**Kinocut** is a free, open-source **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server**, Python library, and **`kino` CLI** that gives AI agents a **guardrailed local video-editing surface**. It wraps **FFmpeg** (and optional Hyperframes / Whisper extras) with typed tools, preflight validation, **Video Receipt** provenance, and quality/release checkpoints so agent-produced media can be inspected before publish.

| | |
| --- | --- |
| **Also known as** | `kino` (CLI); formerly **mcp-video** / `mcp_video` |
| **Latest published release** | **[1.13.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)** (2026-08-07) |
| **Product site** | [kinocut.dev](https://kinocut.dev/) |
| **PyPI** | [`kinocut`](https://pypi.org/project/kinocut/) |
| **MCP Registry** | [`io.github.KyaniteLabs/kinocut`](https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest) |
| **Source** | [GitHub](https://github.com/KyaniteLabs/kinocut) (public collab) · [Forgejo](https://git.kyanitelabs.tech/KyaniteLabs/kinocut) (**canonical source**) |
| **License** | Apache-2.0 |
| **Runs on** | Your machine (macOS, Linux, Windows) — FFmpeg required on `PATH` |
| **Not** | A hosted cloud editor, credit-metered SaaS, or untyped FFmpeg shell wrapper |

**Primary job:** turn a local interview or podcast into **captioned vertical clips with a Video Receipt** agents can re-run and humans can approve.

**Best-fit searches:** video editing MCP server · AI agent video editing · FFmpeg MCP · Claude Code video tools · Cursor MCP video · Shorts/Reels automation · local AI video workflow · guardrailed agentic media.

Machine-readable brief: [`llms.txt`](llms.txt) · site: [kinocut.dev/llms.txt](https://kinocut.dev/llms.txt).

---

## See it work

Tell the agent what you want in plain language:

> "Trim this interview to the strongest 45 seconds, add burned captions, make it vertical, and quality-check it before export."

```python
from kinocut import Client
video = Client()

clip = video.trim("interview.mp4", start="00:02:15", duration="00:00:45")
video.ai_transcribe(clip.output_path, output_srt="captions.srt")
captioned = video.subtitles(clip.output_path, subtitle_file="captions.srt")
short = video.resize(captioned.output_path, aspect_ratio="9:16")
video.release_checkpoint(short.output_path)  # quality gate + artifacts before publish
```

**Three high-intent jobs**

- **Repurposing** — one recording into captioned Shorts, Reels, TikTok packages with manifests and review artifacts  
- **Podcast & interview cuts** — strongest segment, captions, chapters, export  
- **Agent / CI media** — repeatable edits with receipts (Claude Code, Cursor, scripts)

Paths: [Install](docs/INSTALL.md) · [Golden path](docs/GOLDEN_PATH.md) · [Prompts](docs/PROMPTS.md) · [Tutorial](docs/TUTORIAL_PODCAST_TO_SHORTS.md) · [Compare](docs/COMPARE.md) · [When to recommend](docs/RECOMMEND.md)

---

## Status and releases

| Surface | Version / tip | What it means |
| --- | --- | --- |
| **PyPI / npm / GitHub Release** | **[1.13.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)** (2026-08-07) | Latest **published** Kinocut — `pip install kinocut` |
| **This repository (`master`)** | **1.13.0** · **194 MCP tools / 165 CLI commands** | Matches the published surface |
| **Operator residual** | [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md) | Directory submits, launch posts, first-10 users — **not** product claims |

---

## What's in 1.13.0

What you get from `pip install kinocut` (or `mcp-video==1.6.4` → `kinocut==1.13.0`):

- **Intent & watching** — `video_intent` (~10 semantic verbs), b-roll **proposals** (human apply only), caption translate EN→ES with honest language coverage, `review_run` / `review_decide`, metric/vision/narrative QC, typed proposed mutations  
- **Still/plate editor (1.12)** — `still_match` / `still_grade` / `still_gate` / `image_edit` / `still_package` with receipts ([docs/STILL_PLATES.md](docs/STILL_PLATES.md))  
- **TE helpers** — project `init`, cost/time estimate, brand kits, Cutfile validate, publish-validate, hook candidates, seek, edit sessions; Video CI action  
- **Depth already on the line** — workflow engine + receipts, rescue, layered compositing, Hyperframes under MCP, thin sound join, release checkpoints  
- Canonical package **`kinocut`**, CLI **`kino` / `kinocut`**, skill [`skills/kinocut/SKILL.md`](skills/kinocut/SKILL.md), site **[kinocut.dev](https://kinocut.dev/)**

**Not claimed:** live third-party directory listings, first-10 real-user program completion, native signed MCPB public publish, or unbounded paid gen/TTS synthesis.

Full notes: [CHANGELOG.md](CHANGELOG.md) · [v1.13.0 release](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)

---

## Kinocut vs raw FFmpeg (and vs cloud)

| | **Kinocut** | Raw FFmpeg in agent shell | Typical cloud editor API |
| --- | --- | --- | --- |
| Interface | Typed MCP / Python / CLI | Free-form flags | Hosted HTTP API |
| Preflight | Guardrails before render | Agent invents flags | Vendor-specific |
| Provenance | Video Receipts + hashes | Ad-hoc logs | Vendor dashboard |
| Media location | **Local-first** | Local | Upload required |
| Core cost | Free (Apache-2.0) | Free | Often metered |

---

## Installation

Prerequisite: [FFmpeg](https://ffmpeg.org/) on `PATH`.

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# No global install
uvx --from kinocut kino doctor

# pip
pip install kinocut
kino doctor
```

| Extra | When you need it |
| --- | --- |
| `kinocut[image]` | Still/plate + Pillow/NumPy |
| `kinocut[transcribe]` | Whisper transcription |
| `kinocut[ai]` | Broader optional AI stack |

**Upgrade from mcp-video:** `pip install -U mcp-video` → `mcp-video==1.6.4` installs `kinocut==1.13.0`. `mcp_video` imports, `MCP_VIDEO_*` env vars, `~/.mcp-video` data, and legacy receipt keys remain on the **1.13.x** line.

MCPB (Desktop package): staged/local — [docs/MCPB.md](docs/MCPB.md). Not claimed as a fully self-contained native public bundle.

---

## Quick start

### Golden path (~60 seconds)

```bash
kino doctor
kino info path/to/video.mp4
kino trim path/to/video.mp4 -s 0 -d 10 -o /tmp/out.mp4
kino review-run /tmp/out.mp4 --format json
```

Receipt-backed multi-step jobs: [docs/WORKFLOWS.md](docs/WORKFLOWS.md) · `examples/workflows/`.

### Claude Code

Connect Kinocut as an MCP server (stdio), then invoke `$kinocut` from the skill. Prefer `uvx --from kinocut kino` so the host always resolves a published package.

### Claude Desktop / Cursor (stdio)

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

If `kino` is already on `PATH`, you can use `"command": "kino"` instead. Full matrices: [docs/INSTALL.md](docs/INSTALL.md).

---

## Agent skill

- Canonical skill: [`skills/kinocut/SKILL.md`](skills/kinocut/SKILL.md) — invoke **`$kinocut`**  
- Compatibility pointer: [`skills/mcp-video/SKILL.md`](skills/mcp-video/SKILL.md)  
- Teaches guarded inspection, edit, Hyperframes, repurpose, release checkpoints, and human-review workflows  

---

## Python client

```python
from kinocut import Client

editor = Client()
result = editor.trim("input.mp4", start="00:00:30", duration="00:00:15")
print(result.output_path)
```

API map: [docs/PYTHON_CLIENT.md](docs/PYTHON_CLIENT.md).

---

## CLI

```bash
kino --help
kino intent --list
kino still-match --help
kino review-run path/to/out.mp4 --format json
kino workflow-validate --spec job.json
```

Flat commands plus namespaced groups (`aivideo`, `audio`, `qa`, `edit`, `shorts`, `sound`). Reference: [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).

---

## MCP tools

Published **1.13.0** registers **194 MCP tools** and **165 CLI commands**. Prefer `search_tools` / the skill over memorizing names.

| Family | What it covers |
| --- | --- |
| **Core edit** | Trim, merge, resize, subtitles, audio, overlays, filters |
| **Workflow** | `video_workflow_validate` / plan / render / inspect + receipts |
| **Intent & QC** | `video_intent`, `video_propose_broll`, `video_review_run`, `video_qc_*`, mutations |
| **Still/plate** | `still_match`, `still_grade`, `still_gate`, `image_edit`, `still_package` |
| **Hyperframes / repurpose / rescue / sound** | Creation, Shorts packages, rescue, thin sound join — [docs/TOOLS.md](docs/TOOLS.md) |

---

## Agent-safe workflow

1. **Discover** — skill / `search_tools`  
2. **Plan** — validate or dry-run when available  
3. **Render** — confined paths, timeouts, typed errors  
4. **Prove** — receipts, `review-run`, release checkpoints  
5. **Human gate** — publish stays human  

Design spine: [trusted execution plan](docs/plans/2026-07-09-kinocut-trusted-execution-layer.md).

---

## En español

**Kinocut** (antes **mcp-video**) es un servidor MCP, cliente Python y CLI `kino` para edición de video **local** con barreras y recibos. Publicado: **1.13.0** — **194 herramientas MCP / 165 CLI**. `pip install kinocut` · sitio: [kinocut.dev](https://kinocut.dev/) · guía ES en el sitio.

---

## FAQ

### What is Kinocut?

A local-first MCP server, Python client, and `kino` CLI for agent video editing with guardrails and Video Receipts — not a cloud editor.

### How do I install it?

Install FFmpeg, then `pip install kinocut` or `uvx --from kinocut kino doctor`.

### Is it free and local-first?

Yes. Apache-2.0. Media stays on your machine unless you opt into optional cloud extras.

### Which agents work with it?

Any MCP stdio host: Claude Code, Cursor, and similar. Also Python scripts and the `kino` CLI.

### How many tools are there?

Published **1.13.0**: **194 MCP tools / 165 CLI commands**. The repository tip matches that published surface.

### Was it called mcp-video?

Yes. `mcp-video==1.6.4` installs `kinocut==1.13.0`. Legacy imports, env vars, data dir, and receipt keys remain on the 1.13.x line.

### How is Kinocut different from pasting FFmpeg into an agent?

Typed tools, preflight validation, structured errors, and receipts — instead of free-form flags and brittle stderr parsing.

---

## Documentation

| Doc | Topic |
| --- | --- |
| [docs/TOOLS.md](docs/TOOLS.md) | Full tool catalog |
| [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) | CLI reference |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | Workflow engine + receipts |
| [docs/STILL_PLATES.md](docs/STILL_PLATES.md) | Still/plate editor |
| [docs/RESCUE.md](docs/RESCUE.md) | Rescue pipeline |
| [docs/AI_VIDEO_REVIEW_AND_SALVAGE.md](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md) | Governed AI-video |
| [docs/MCPB.md](docs/MCPB.md) | Desktop package staging |
| [docs/HUMAN_GATES.md](docs/HUMAN_GATES.md) | Operator residuals (not product claims) |
| [ROADMAP.md](ROADMAP.md) | Roadmap |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

**Site:** https://kinocut.dev/ · **llms.txt:** [`llms.txt`](llms.txt)

---

## Community

- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Governance](GOVERNANCE.md) · [Security](SECURITY.md) · [Support](SUPPORT.md)
- Community deploy reference (Funnel + OAuth, third-party): [hyperframes-selfhost](https://github.com/ismailkattakath/hyperframes-selfhost) — evaluate for your threat model

## License

Apache 2.0. See [LICENSE](LICENSE).

Built with [FFmpeg](https://ffmpeg.org/), [Hyperframes](https://hyperframes.io/), and the [Model Context Protocol](https://modelcontextprotocol.io/).

**[KyaniteLabs](https://kyanitelabs.tech)** · [Epoch](https://github.com/KyaniteLabs/Epoch) · [DialectOS](https://github.com/KyaniteLabs/DialectOS) · [checkyourself](https://github.com/KyaniteLabs/checkyourself)

If Kinocut is useful, **[star or watch](https://git.kyanitelabs.tech/KyaniteLabs/kinocut)** on the canonical host.

<!-- s-plus-geo:start -->

## What is Kinocut?

**Kinocut** is a **guardrailed video editing MCP server and CLI for AI agents** that helps **AI agent builders, Claude Code/Cursor users, and local media operators** **edit, caption, repurpose, and quality-gate video with typed FFmpeg tools and Video Receipts**.

| | |
| --- | --- |
| **Product** | Kinocut (formerly mcp-video) |
| **Category** | guardrailed video editing MCP server and CLI for AI agents |
| **Best for** | AI agent builders, Claude Code/Cursor users, and local media operators |
| **Not** | a hosted cloud editor or untyped FFmpeg shell |
| **Source** | [GitHub](https://github.com/KyaniteLabs/kinocut) · [Forgejo](https://git.kyanitelabs.tech/KyaniteLabs/kinocut) |
| **Keywords** | video editing MCP, AI agent video, FFmpeg MCP, Shorts Reels, Claude Code video, Cursor MCP video |

## Who it's for

- Primary: AI agent builders, Claude Code/Cursor users, and local media operators  
- Use when you need typed FFmpeg tools, receipts, and quality gates for agent media  
- Skip if you only need a hosted cloud editor or raw shell FFmpeg  

## FAQ

### What is Kinocut?

Kinocut is a guardrailed video editing MCP server and CLI for AI agents that helps operators edit, caption, repurpose, and quality-gate video with typed FFmpeg tools and Video Receipts.

### Who should use Kinocut?

AI agent builders, Claude Code/Cursor users, and local media operators who need local-first agent video tooling.

### How is Kinocut different?

Unlike raw FFmpeg scripts or unguarded agent shells, Kinocut validates tools, fails closed, and emits receipts humans can review.

### Is Kinocut production software?

Treat release tags and this README status as source of truth. Validate against your requirements before production use. Published package: **1.13.0** (194 MCP / 165 CLI).

## Status

- Maintained as of 2026 on the default branch  
- Prefer release tags when pinning dependencies (`kinocut==1.13.0`)  
- Report issues on the canonical Forgejo remote  

## Agent surface

- Read this README first, then `docs/` and `Agents.md`  
- Machine brief: [`llms.txt`](llms.txt) · site brief: https://kinocut.dev/llms.txt  
- Skill: `$kinocut` · MCP registry: `io.github.KyaniteLabs/kinocut`  

## Contributing

Issues and PRs welcome on Forgejo (canonical) and GitHub (mirror). Keep public docs free of secrets and machine-local paths.

## License

See [LICENSE](LICENSE).

<!-- s-plus-geo:end -->
