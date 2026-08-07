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
  <a href="#mcp-tools">Tools</a> ·
  <a href="docs/TOOLS.md">Tool reference</a> ·
  <a href="#agent-skill">Skill</a> ·
  <a href="https://kinocut.dev/">kinocut.dev</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="llms.txt">llms.txt</a>
</p>

---

## What is Kinocut?

**Kinocut** is a free, open-source **[MCP](https://modelcontextprotocol.io/) server**, Python library, and **`kino` CLI** that gives AI agents a **guardrailed local video-editing surface**. It wraps **FFmpeg** (and optional Hyperframes / Whisper extras) with typed tools, preflight validation, **Video Receipt** provenance, and quality/release checkpoints.

| | |
| --- | --- |
| **Also known as** | `kino` (CLI); formerly **mcp-video** / `mcp_video` |
| **Latest published release** | **[1.13.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)** (2026-08-07) |
| **Product site** | [kinocut.dev](https://kinocut.dev/) |
| **PyPI** | [`kinocut`](https://pypi.org/project/kinocut/) |
| **MCP Registry** | [`io.github.KyaniteLabs/kinocut`](https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest) |
| **Source** | [GitHub](https://github.com/KyaniteLabs/kinocut) (mirror) · [Forgejo](https://git.kyanitelabs.tech/KyaniteLabs/kinocut) (**canonical**) |
| **License** | Apache-2.0 |
| **Runs on** | Your machine — FFmpeg required on `PATH` |
| **Not** | A hosted cloud editor, credit-metered SaaS, or untyped FFmpeg shell wrapper |

**Primary job:** turn a local interview or podcast into **captioned vertical clips with a Video Receipt** agents can re-run and humans can approve.

---

## See it work

```python
from kinocut import Client
video = Client()

clip = video.trim("interview.mp4", start="00:02:15", duration="00:00:45")
video.ai_transcribe(clip.output_path, output_srt="captions.srt")
captioned = video.subtitles(clip.output_path, subtitle_file="captions.srt")
short = video.resize(captioned.output_path, aspect_ratio="9:16")
video.release_checkpoint(short.output_path)
```

Common paths: **repurposing** (Shorts/Reels packages), **interview cuts**, **agent/CI media** with receipts.

Deep dives: [Install](docs/INSTALL.md) · [Golden path](docs/GOLDEN_PATH.md) · [Prompts](docs/PROMPTS.md) · [Tutorial](docs/TUTORIAL_PODCAST_TO_SHORTS.md) · [Compare](docs/COMPARE.md)

---

## Status and releases

| Surface | Version | Meaning |
| --- | --- | --- |
| **PyPI / npm / GitHub Release** | **[1.13.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)** | Latest **published** package |
| **This repository (`master`)** | **1.13.0** · **194 MCP tools / 165 CLI commands** | Matches published surface |
| **Operator residual** | See [`docs/HUMAN_GATES.md`](docs/HUMAN_GATES.md) | Directory submits, launch posts, first-10 users — not product code |

---

## What's in 1.13.0

Install: `pip install kinocut` (or `mcp-video==1.6.4` → installs `kinocut==1.13.0`).

- **Intent / watching / TE** — `video_intent`, b-roll proposals (human apply only), caption translate + language coverage, review_run/decide, metric/vision/narrative QC, mutations, init/estimate/brand/cutfile, publish-validate, hooks, seek, edit sessions
- **Still/plate (1.12)** — match / grade / gate / image-edit / package with receipts ([docs/STILL_PLATES.md](docs/STILL_PLATES.md))
- **Workflows, rescue, compositing, Hyperframes, sound join** — as documented in [CHANGELOG.md](CHANGELOG.md)
- Canonical **`kino` / `kinocut`** CLI, skill [`skills/kinocut/SKILL.md`](skills/kinocut/SKILL.md), site **kinocut.dev**

**Not claimed:** live third-party directory listings, first-10 real-user program completion, native signed MCPB public publish, or unbounded paid gen/TTS.

Full notes: [CHANGELOG.md](CHANGELOG.md) · [v1.13.0](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.13.0)

---

## Installation

Prerequisite: [FFmpeg](https://ffmpeg.org/) on `PATH`.

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Run without global install
uvx --from kinocut kino doctor

# Or pip
pip install kinocut
kino doctor
```

| Extra | When |
| --- | --- |
| `kinocut[image]` | still/plate + Pillow/NumPy stack |
| `kinocut[transcribe]` | Whisper transcription |
| `kinocut[ai]` | broader optional AI stack |

Upgrade from mcp-video: `pip install -U mcp-video` installs matching Kinocut; `mcp_video` imports and `MCP_VIDEO_*` env vars remain supported on the 1.13.x line.

MCPB staging: [docs/MCPB.md](docs/MCPB.md) (not a fully self-contained native public bundle claim).

---

## Quick start

### Golden path (~60s)

```bash
kino doctor
kino info path/to/video.mp4
kino trim path/to/video.mp4 -s 0 -d 10 -o /tmp/out.mp4
```

Receipt-backed workflow: [docs/WORKFLOWS.md](docs/WORKFLOWS.md) · examples under `examples/workflows/`.

### Claude Code / Desktop / Cursor

Add stdio server via `uvx --from kinocut kino` (or `kino` if installed). Skill: `$kinocut` from [`skills/kinocut/SKILL.md`](skills/kinocut/SKILL.md). Config snippets: [docs/INSTALL.md](docs/INSTALL.md).

---

## Python client

```python
from kinocut import Client
c = Client()
print(c.trim("in.mp4", start="0", duration="5").output_path)
```

More: [docs/PYTHON_CLIENT.md](docs/PYTHON_CLIENT.md).

---

## CLI

```bash
kino --help
kino intent --list
kino review-run path/to/out.mp4 --format json
kino still-match --help
```

Flat commands plus namespaced groups (`aivideo`, `audio`, `qa`, `edit`, `shorts`, `sound`). Reference: [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).

---

## MCP tools

Published **1.13.0** exposes **194 MCP tools** and **165 CLI commands**. Use `search_tools` / agent discovery rather than memorizing the full list.

| Family | Examples |
| --- | --- |
| Core edit | trim, merge, resize, subtitles, audio, overlays |
| Workflow | `video_workflow_validate` / plan / render / inspect |
| Intent & QC | `video_intent`, `video_review_run`, `video_qc_*`, `video_propose_broll` |
| Still/plate | `still_match`, `still_grade`, `still_gate`, `image_edit`, `still_package` |
| Hyperframes / repurpose / rescue / sound | see [docs/TOOLS.md](docs/TOOLS.md) |

---

## Agent-safe workflow

1. **Discover** — `search_tools` / skill  
2. **Plan** — validate or dry-run when available  
3. **Render** — confined paths, timeouts, typed errors  
4. **Prove** — receipts, `review-run`, release checkpoints  
5. **Human gate** — publish decisions stay human  

Long-form design: [docs/plans/2026-07-09-kinocut-trusted-execution-layer.md](docs/plans/2026-07-09-kinocut-trusted-execution-layer.md).

---

## En español

Kinocut es un servidor MCP de edición de video local para agentes (antes mcp-video). Publicado: **1.13.0** — **194 herramientas MCP / 165 CLI**. `pip install kinocut` · sitio: [kinocut.dev](https://kinocut.dev/).

---

## FAQ

### What is Kinocut?

A local-first MCP server, Python client, and `kino` CLI for agent video editing with guardrails and receipts—not a cloud editor.

### How do I install it?

Install FFmpeg, then `pip install kinocut` or `uvx --from kinocut kino doctor`.

### Is it free and local-first?

Yes. Apache-2.0; media stays on your machine unless you choose optional cloud extras.

### How many tools are there?

Published **1.13.0**: **194 MCP tools / 165 CLI commands**. Tip matches published.

### Was it called mcp-video?

Yes. `mcp-video==1.6.4` installs `kinocut==1.13.0`. Legacy imports/env/data keys remain on the 1.13.x line.

### Kinocut vs raw FFmpeg in an agent shell?

Typed tools, preflight, and receipts vs free-form flags and ad-hoc logs.

---

## Documentation

| Doc | Topic |
| --- | --- |
| [docs/TOOLS.md](docs/TOOLS.md) | Tool catalog |
| [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) | CLI |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | Workflow engine |
| [docs/STILL_PLATES.md](docs/STILL_PLATES.md) | Still/plate editor |
| [docs/RESCUE.md](docs/RESCUE.md) | Rescue pipeline |
| [docs/AI_VIDEO_REVIEW_AND_SALVAGE.md](docs/AI_VIDEO_REVIEW_AND_SALVAGE.md) | Governed AI-video |
| [docs/MCPB.md](docs/MCPB.md) | Desktop package staging |
| [docs/HUMAN_GATES.md](docs/HUMAN_GATES.md) | Operator residuals |
| [ROADMAP.md](ROADMAP.md) | Roadmap |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

Site: **https://kinocut.dev/** · machine brief: [`llms.txt`](llms.txt)

---

## Community

- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Governance](GOVERNANCE.md) · [Security](SECURITY.md)
- Community deploy pointer (Funnel/OAuth stack): [hyperframes-selfhost](https://github.com/ismailkattakath/hyperframes-selfhost) (third-party; evaluate your threat model)

## License

Apache 2.0. See [LICENSE](LICENSE).

Built with [FFmpeg](https://ffmpeg.org/), [Hyperframes](https://hyperframes.io/), and the [Model Context Protocol](https://modelcontextprotocol.io/).

**[KyaniteLabs](https://kyanitelabs.tech)** · [Epoch](https://github.com/KyaniteLabs/Epoch) · [DialectOS](https://github.com/KyaniteLabs/DialectOS) · [checkyourself](https://github.com/KyaniteLabs/checkyourself)

If Kinocut is useful, **[star or watch](https://git.kyanitelabs.tech/KyaniteLabs/kinocut)** on the canonical host.

<!-- s-plus-geo:start -->

## What is Kinocut?

**Kinocut** is a **guardrailed video editing MCP server and CLI for AI agents** that helps **AI agent builders, Claude Code/Cursor users, and local media operators** **edit, caption, repurpose, and quality-gate video with typed FFmpeg tools**.

| | |
| --- | --- |
| **Product** | Kinocut |
| **Category** | guardrailed video editing MCP server and CLI for AI agents |
| **Best for** | AI agent builders, Claude Code/Cursor users, and local media operators |
| **Not** | a hosted cloud editor or untyped FFmpeg shell |
| **Source** | [GitHub](https://github.com/KyaniteLabs/kinocut) · [Forgejo](https://git.kyanitelabs.tech/KyaniteLabs/kinocut) |
| **Keywords** | video editing MCP, AI agent video, FFmpeg MCP, Shorts Reels |

## Who it's for

- Primary: AI agent builders, Claude Code/Cursor users, and local media operators
- Use when you need typed FFmpeg tools with receipts and quality gates
- Skip if you need a hosted cloud editor or raw shell FFmpeg only

## FAQ

### What is Kinocut?

Kinocut is a guardrailed video editing MCP server and CLI for AI agents.

### Who should use Kinocut?

AI agent builders, Claude Code/Cursor users, and local media operators.

### How is Kinocut different?

Unlike raw FFmpeg scripts or unguarded agent shells, Kinocut validates tools and emits receipts.

### Is Kinocut production software?

Treat release tags and this README status as source of truth. Validate against your requirements before production use.

## Status

- Maintained as of 2026 on the default branch
- Prefer release tags when pinning dependencies
- Report issues on the canonical Forgejo remote

## Agent surface

- Read this README first, then `docs/` and `Agents.md`
- Machine brief: [`llms.txt`](llms.txt)
- Skill: `$kinocut` · MCP: `io.github.KyaniteLabs/kinocut`

## Contributing

Issues and PRs welcome on Forgejo (canonical) / GitHub (mirror). Keep public docs free of secrets and machine-local paths.

## License

See [LICENSE](LICENSE).

<!-- s-plus-geo:end -->
