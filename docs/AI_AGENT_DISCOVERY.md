# AI Agent Discovery

This document is the short, explicit discovery map for agents, answer engines, and humans trying to understand `mcp-video`.

## Canonical Positioning

`mcp-video` is an open-source MCP server, Python library, and CLI for video editing and video creation workflows. It wraps FFmpeg, PUSHING CREATION-style planning, Hyperframes authoring, and local repurposing packages with 119 structured tool calls plus preflight guardrails so agents can edit, plan, render, and package video without inventing brittle shell commands or silently producing bad media.

## Best Queries To Match

- video editing MCP server
- MCP server for FFmpeg
- AI agent video editing
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
- mcp-video public agent skill

## Best Entry Points

- `README.md` - install, quick start, tools, CLI, Python client, workflows.
- `skills/mcp-video/SKILL.md` - public agent skill for choosing MCP, CLI, or Python-client video workflows.
- `CLAUDE.md` - Layer 0 identity: what this project is, where to find staged pipelines.
- `llms.txt` - compact machine-readable project map.
- `mcp_video/server.py` - MCP tool registration layer, including `search_tools`.
- `mcp_video/engine.py` - core FFmpeg operations.
- `mcp_video/filter_guardrails.py`, `merge_guardrails.py`, and `audio_guardrails.py` - preflight checks for risky media operations.
- `mcp_video/creation_engine.py` - PUSHING CREATION-style project, style-pack, storyboard, and shot-prompt helpers.
- `mcp_video/client/` - Python client mixins. Use `Client.inspect()`, `Client.pipeline()`, and `Client.release_checkpoint()` for guarded agent workflows.
- `mcp_video/client/meta.py` - Client-side tool discovery (`search_tools`).
- `mcp_video/client/hyperframes.py` - Hyperframes client mixin.
- `mcp_video/client/media.py` - media repurposing client helpers.
- `mcp_video/engine_repurpose.py` - local repurposing manifest and render orchestration.
- `mcp_video/__main__.py` - CLI.
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
claude mcp add mcp-video -- uvx --from mcp-video mcp-video
```

Claude Desktop:

```json
{
  "mcpServers": {
    "mcp-video": {
      "command": "uvx",
      "args": ["--from", "mcp-video", "mcp-video"]
    }
  }
}
```

Cursor:

```json
{
  "mcpServers": {
    "mcp-video": {
      "command": "uvx",
      "args": ["--from", "mcp-video", "mcp-video"]
    }
  }
}
```

Agent skill:

```text
Use $mcp-video to inspect this media, plan guarded edits, produce release artifacts, and keep a human review gate before publishing.
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

- [Official MCP Registry](https://registry.modelcontextprotocol.io/servers/io.github.KyaniteLabs/mcp-video) — metadata in `server.json` at the repo root, published from the release workflow via `mcp-publisher` after PyPI publication. Identifier: `io.github.KyaniteLabs/mcp-video`.
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
- MCP Registry publication status for `io.github.KyaniteLabs/mcp-video`.
