# AI Agent Discovery

This document is the short, explicit discovery map for agents, answer engines, and humans trying to understand `Kinocut`.

## Canonical Positioning

`Kinocut` is an open-source MCP server, Python library, and CLI for video editing and video creation workflows. It wraps FFmpeg, an agent workflow engine (plan/validate/render/resume/inspect multi-step jobs with provenance receipts), PUSHING CREATION-style planning, Hyperframes authoring, and local repurposing packages with 135 structured tool calls plus preflight guardrails so agents can edit, plan, render, and package video without inventing brittle shell commands or silently producing bad media.

## Best Queries To Match

- video editing MCP server
- MCP server for FFmpeg
- AI agent video editing
- agent video workflow engine
- multi-step video job with provenance receipts
- resumable video render workflow MCP
- Claude Code video editing MCP
- Cursor MCP video editing
- programmatic video editing Python
- cinematic video prompt storyboard MCP
- AI video style pack workflow
- Hyperframes MCP integration
- Hyperframes TTS transcription background removal MCP
- video repurposing MCP Shorts Reels TikTok
- FFmpeg tools for AI agents
- guardrailed video editing MCP server
- safe agentic media automation
- Kinocut public agent skill

## Best Entry Points

- `README.md` - install, quick start, tools, CLI, Python client, workflows.
- `docs/WORKFLOWS.md` - agent workflow engine: job-spec schema, `@ref` grammar, op allowlist, variants, resume semantics, cleanup, and privacy.
- `docs/VIDEO_RECEIPT.md` - workflow/`layer_plan` receipt kinds, `schema_version` policy, and the `receipt_kind` discriminator.
- `skills/kinocut/SKILL.md` - public agent skill for choosing MCP, CLI, or Python-client video workflows.
- `CLAUDE.md` - Layer 0 identity: what this project is, where to find staged pipelines.
- `llms.txt` - compact machine-readable project map.
- `kinocut/server.py` - MCP tool registration layer, including `search_tools`.
- `kinocut/engine.py` - core FFmpeg operations.
- `kinocut/filter_guardrails.py`, `merge_guardrails.py`, and `audio_guardrails.py` - preflight checks for risky media operations.
- `kinocut/creation_engine.py` - PUSHING CREATION-style project, style-pack, storyboard, and shot-prompt helpers.
- `kinocut/client/` - Python client mixins. Use `Client.inspect()`, `Client.pipeline()`, and `Client.release_checkpoint()` for guarded agent workflows.
- `kinocut/client/meta.py` - Client-side tool discovery (`search_tools`).
- `kinocut/client/hyperframes.py` - Hyperframes client mixin.
- `kinocut/client/media.py` - media repurposing client helpers.
- `kinocut/engine_repurpose.py` - local repurposing manifest and render orchestration.
- `kinocut/__main__.py` - CLI.
- `workflows/CONTEXT.md` - Layer 1 routing: which ICM workflow to use.
- `workflows/01-social-media-clip/CONTEXT.md` - Stage contract for social clip production.
- `workflows/02-podcast-clip/CONTEXT.md` - Stage contract for podcast highlight production.
- `workflows/03-explainer-video/CONTEXT.md` - Stage contract for explainer video production.
- `server.json` - MCP Registry metadata for the PyPI package.
- `CONTRIBUTING.md` - contribution and testing rules.
- `SECURITY.md` - private vulnerability reporting.

## Agent-Friendly Install Snippets

Claude Code:

```bash
claude mcp add Kinocut -- uvx --from kinocut kino
```

Claude Desktop:

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

Cursor:

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

Agent skill:

```text
Use $kinocut to inspect this media, plan guarded edits, produce release artifacts, and keep a human review gate before publishing.
```

## What Agents Should Not Do

- Do not bypass guardrails for filter parameters, merge compatibility, audio mix settings, overlay timing/opacity, animated text timing/overflow, or grid/split-screen mismatches.
- Do not interpolate user strings directly into FFmpeg filter strings.
- Do not add generated media or local workspace artifacts to git.
- Do not break existing MCP tool signatures.
- Do not move business logic into `server.py`; keep it in engine modules.
- Do not add dependencies just to wrap a single command.
- Do not write output next to source files; use temp directories or explicit output paths.
- Do not claim ICM folder structure is used for core code; it is layered on top (`workflows/`).

## Registry And Directory Targets

High-leverage listing targets:

- [Official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers/io.github.KyaniteLabs%2Fkinocut/versions/latest) - active release metadata for `io.github.KyaniteLabs/kinocut`, published from `server.json` after package publication.
- [Directory rebrand status](DIRECTORY_REBRAND_STATUS.md) - live reconciliation ledger for stale former-name listings and downstream mirrors.
- [Glama MCP Registry](https://glama.ai/mcp/servers) — Submit via GitHub repo URL.
- [Smithery](https://smithery.ai) — Submit via GitHub repo URL once the official registry and Glama listings are fresh.
- [MCP.so](https://mcp.so) — Submit via GitHub repo URL.
- [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers) — Submit via PR.
- GitHub topics for `mcp`, `mcp-server`, `ffmpeg`, `video-editing`, `ai-agents`.

## Measurement

Track:

- GitHub stars and forks.
- PyPI downloads.
- GitHub Pages traffic.
- Issues opened by real users.
- Discussion posts and show-and-tell examples.
- Mentions in MCP directories and AI answer results.
- MCP Registry publication status for `io.github.KyaniteLabs/kinocut`.
