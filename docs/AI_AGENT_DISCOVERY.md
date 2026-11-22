# AI Agent Discovery

This document is the short, explicit discovery map for agents, answer engines, and humans trying to understand `Kinocut`.

## Canonical Positioning

`Kinocut` is an open-source MCP server, Python client and `kino` CLI for guardrailed
video editing by AI agents. It wraps FFmpeg in typed, preflight-checked tools that write
new files, run quality gates and record Video Receipts.

- **Published 2.0.1:** 206 MCP tools / 177 CLI commands with `KINOCUT_TOOLS=all`;
  18 tools listed by default: an 8-tool hot path, eight operation families, and
  `list_operations` / `describe_operation`, which reach every other operation.
- **Development (unreleased #458):** 208 MCP tools / 178 CLI commands. Pass spoken edit
  direction verbatim to `video_direct`; review assumptions and any question, then call
  `video_direct_apply` with `confirm=true` after user approval.

Beyond core editing it covers Shorts and Reels repurposing, a resumable workflow engine,
video rescue, AI-video review and salvage, 360 dual-cam assembly (through `video_intent`,
no extra MCP tool), product matte, still plates, bounded sound operations, Hyperframes
and local Revideo creation (a custom Revideo scene is trusted executable TypeScript),
and a `video_review_card` for approving a cut in Hermes Desktop chat.

## Best Queries To Match

- video editing MCP server
- MCP server for FFmpeg
- AI agent video editing
- guardrailed video editing MCP server
- safe agentic media automation
- Claude Code video editing MCP
- Cursor MCP video editing
- programmatic video editing Python
- multi-step video job with provenance receipts
- resumable video render workflow MCP
- video repurposing MCP Shorts Reels TikTok
- Hyperframes MCP integration
- FFmpeg tools for AI agents
- Kinocut public agent skill

## Best Entry Points

- `README.md` - install, tool surface, review, capabilities, releases.
- `docs/status/NOW.md` - current published-versus-development truth and remaining human gates.
- `docs/MCP_TOOL_FAMILIES.md` - the default surface: hot path, families and discovery calls.
- `docs/TOOLS.md` - every MCP tool by name.
- `docs/WORKFLOWS.md` - workflow engine: job-spec schema, `@ref` grammar, op allowlist, variants, resume, cleanup and privacy.
- `docs/VIDEO_RECEIPT.md` - receipt kinds, `schema_version` policy and the `receipt_kind` discriminator.
- `docs/AI_VIDEO_REVIEW_AND_SALVAGE.md` - exact-asset review, protection, body-swap, salvage and re-review.
- `docs/360_ASSEMBLY.md` - Insta360 X4 stitched MP4 to propose, approve and render.
- `skills/kinocut/SKILL.md` - public agent skill for choosing MCP, CLI or Python-client workflows.
- `llms.txt` - compact machine-readable project map.
- `kinocut/tool_registry.py` - hot path, profiles and `KINOCUT_TOOLS` selection.
- `kinocut/tool_families.py` - typed operation families.
- `kinocut/server.py` - MCP tool registration facade.
- `kinocut/engine.py` - core FFmpeg operations facade.
- `kinocut/filter_guardrails.py`, `merge_guardrails.py` and `audio_guardrails.py` - preflight checks for risky media operations.
- `kinocut/client/` - Python client mixins. `Client.inspect(name)` describes a method, `Client.pipeline()` chains steps and `Client.release_checkpoint()` gates the result.
- `kinocut/engine_repurpose.py` - local repurposing manifest and render orchestration.
- `kinocut/__main__.py` - CLI entry point.
- `workflows/CONTEXT.md` - routing to the staged production workflows in `workflows/`.
- `server.json` - MCP Registry metadata for the PyPI package.
- `CONTRIBUTING.md` - contribution and testing rules.
- `SECURITY.md` - private vulnerability reporting.

## Agent-Friendly Install Snippets

Claude Code:

```bash
claude mcp add kinocut -- uvx --from kinocut==2.0.1 kino --mcp
```

Claude Desktop:

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
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
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
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
- Do not claim the staged `workflows/` folders are used for core code; they are layered on top.
- Do not treat a draft implementation snapshot, automated finding, or repository test receipt as human creative approval or release authority.

## Registry And Directory Targets

High-leverage listing targets:

- [Official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers/tech.kyanitelabs%2Fkinocut/versions/latest) - `tech.kyanitelabs/kinocut` reports published 2.0.1 as a local stdio package (verified 2026-10-27).
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
- MCP Registry publication status for `tech.kyanitelabs/kinocut`.
