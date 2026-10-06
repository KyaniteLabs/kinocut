# Frequently Asked Questions

## What is Kinocut?

Kinocut is an open-source MCP server, Python library, and CLI that wraps FFmpeg, PUSHING CREATION-style planning, Hyperframes, and local repurposing workflows for AI-agent video editing and creation. Core FFmpeg editing runs locally and the code is licensed under Apache-2.0. Optional models and authoring tools have their own dependencies; the AI host or an explicitly configured service may have separate data-transfer and cost requirements.

## What is MCP?

MCP (Model Context Protocol) is a standard protocol that lets AI agents like Claude Code and Cursor call external tools through a structured interface. Think of it as "USB-C for AI tools" — a universal connector between agents and capabilities.

## Is Kinocut on the MCP Registry?

Current maintenance publication (2026-10-05): PyPI/npm and GitHub release report **1.16.1**; compatibility shim **1.6.16** pins it. The initial publication gate read MCP Registry 1.16.1; later reads timed out. Website 1.16.1 source is prepared, not deployed. The dated checkpoint below remains historical.

Kinocut's canonical identifier is `io.github.KyaniteLabs/kinocut`, with release metadata in `server.json`. The [official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest), PyPI, npm and GitHub release report 1.16.0 (verified 2026-10-02); compatibility package `mcp-video==1.6.15` pins `kinocut==1.16.0`. The [live website](https://kinocut.dev/) also showed 1.16.0, 203 MCP tools and 177 CLI commands on 2026-10-05. Final owner acceptance and fleet rollout remain separately unverified. GitHub is the canonical product repository; the website has its own Forgejo source authority.

## Which AI agents work with Kinocut?

Any MCP-compatible agent: Claude Code, Cursor, Windsurf, Cline, and any client that supports the MCP protocol. The server runs as a stdio transport, which is the standard MCP transport mode.

## Do I need FFmpeg installed?

Yes. FFmpeg must be installed and available on your `PATH`. On macOS: `brew install ffmpeg`. On Ubuntu: `sudo apt install ffmpeg`. The package does not bundle FFmpeg itself.

## Does it work on Windows?

Yes. Kinocut works on macOS, Linux, and Windows as long as FFmpeg is installed and accessible.

## What video formats are supported?

Support depends on the operation, its admitted containers/codecs and the installed FFmpeg build. Common workflows use MP4, WebM, MOV, AVI, MKV and GIF. A decoder accepting a file does not mean every edit or output codec is supported; consult the tool parameters and run `kino doctor`.

## Can I use it without an AI agent?

Yes. Kinocut has three interfaces: MCP server (for agents), Python client (for scripts), and CLI (for terminal use). You can use any of them independently.

## How do I install it?

```bash
pip install kinocut
```

For AI features like transcription and upscaling, install the extras:

```bash
pip install "kinocut[ai]"
```

## How do I connect Kinocut to Claude Code?

Install FFmpeg and [uv](https://docs.astral.sh/uv/getting-started/installation/), then register the local stdio server:

```bash
claude mcp add kinocut -- uvx --from kinocut kino --mcp
```

Run `kino doctor` in an installed Kinocut environment to inspect dependencies. The explicit `--mcp` selects server mode; invoking `kino` without a command also selects MCP today. See [installation](INSTALL.md) and [integrations](INTEGRATIONS.md) for other hosts.

## Why use Kinocut rather than invoking FFmpeg directly?

Kinocut supplies structured tools, path and parameter validation, bounded subprocess execution and operation-specific preflight checks. Workflows can record Video Receipts with source/output hashes, tool calls and review status. This helps an agent inspect and reproduce an edit; it does not replace FFmpeg expertise, guarantee a creative result or grant human approval. See [receipt contracts](VIDEO_RECEIPT.md) and [quality evidence](QUALITY_EVIDENCE.md).

## Does local-first mean no data leaves my machine?

Core media edits execute locally. Your AI host decides which prompts, tool results or media it shares, and optional services have their own policies. Review the host permissions and configured providers before handling sensitive media; local-first alone is not a zero-transfer guarantee.

## Is mcp-video a separate product?

No. Kinocut is the renamed project. The compatibility package and `mcp-video` command/`mcp_video` import remain supported. New installations should use `kinocut`, `kino` and `from kinocut import Client`; historical release evidence retains its original names. See [the rename guide](RENAME.md).

## What are the AI-powered features?

Optional model-backed operations include Whisper transcription, stem separation and upscaling. The wider AI-labelled area also contains deterministic helpers such as silence/scene detection, color grading and spatial audio positioning; the label does not mean each operation invokes a model. Check the required extra and backend with `kino doctor`. Planning or retained frame sampling is separate from completed inference; see [quality evidence and capability limits](QUALITY_EVIDENCE.md).

## What tool areas does it cover?

Kinocut covers Meta / Discovery, Cinematic Creation, Core Editing, AI-Powered media, Hyperframes, local repurposing, Audio Synthesis, Visual Effects, Transitions, Layout & Motion Graphics, Analysis, and Image Analysis. Use `search_tools` when an agent needs to find the right operation without loading the whole registry.

## Can it edit Insta360 X4 360 video?

Yes — from a **stitched 360 MP4**, not a raw `.insv`. `video_intent` with a 360/desk/table goal (or `Client.propose_360_assembly`) writes a reviewable `360_assembly_plan`. Approve, then render split / switch / PiP / single. There is no extra MCP tool name. This is available in the published `kinocut==1.16.1`. See [360_ASSEMBLY.md](360_ASSEMBLY.md).

## What are the cinematic creation tools?

The cinematic creation tools add a PUSHING CREATION-compatible pre-production workflow: `video_project_create` scaffolds a project with `style.md`, `storyboard.md`, and `refs/`; `style_pack_read` parses STYLE_ and NEG_ blocks; `storyboard_read` parses shot rows; and `shot_prompt_render` expands camera/lens direction and style references into generic positive and negative prompts. The result explicitly reports `prompt_dialect="generic"` and `model_dialect_compiled=false`; it does not compile a model-specific dialect or call a generation provider.

## What do the Hyperframes and repurposing tools add?

Hyperframes tools cover project scaffolds, renders, snapshots, layout inspection, catalog blocks, website capture, local TTS, transcription import, background removal, diagnostics, and benchmarking. Repurposing tools create dry-run manifests or local platform packages for Shorts, Reels, TikTok, and YouTube-style variants, including thumbnails, storyboards, and optional release checkpoints.

## Can I cut a product out of a turntable or tabletop video?

Yes, on the same `hyperframes-remove-background` command. The default model is **people** (`u2net_human_seg`). For products and other objects pass `--model birefnet-general` after `pip install "kinocut[object-matte]"`. That optional extra is available in the published **1.16.1** (first shipped in 1.15.1). `--info` lists models without downloading. No new MCP tool name. See [PRODUCT_MATTE.md](PRODUCT_MATTE.md).

## Is it free?

Kinocut has no core license fee and is open-source under Apache-2.0. Local hardware, electricity and hosting still cost money; your AI host, optional services or separately licensed models may incur fees. There is no universal zero-cost claim.

## How fast is it?

Runtime depends on source duration/resolution, codec, requested operations, hardware, optional models and verification passes. Some operations copy streams; others decode and re-encode. Measure the intended workload rather than assuming a universal speedup or equivalence to an unverified FFmpeg command.

## Can I use it in production?

Yes. Kinocut has comprehensive error handling with structured error types, input validation, FFmpeg timeout protection, and CI coverage for package and repository readiness. It's used in CI/CD pipelines for automated video quality checks.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full guide. The short version: fork, branch, write tests, submit a PR. All PRs need passing CI.


## Who is Kinocut for?

1. **Agent users** — Claude Code / Cursor operators who want structured video tools.
2. **Media operators** — podcast/social teams automating cuts with human approval.
3. **Stack evaluators** — platform engineers comparing local MCP video options.

See [RECOMMEND.md](RECOMMEND.md) and [COMPARE.md](COMPARE.md).

## Is there a paid enterprise tier?

Not as of the published open-source core. Apache-2.0; see [ENTERPRISE.md](ENTERPRISE.md) for commercial clarity.
