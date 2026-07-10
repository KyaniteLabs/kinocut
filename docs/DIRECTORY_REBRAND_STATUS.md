# Directory Rebrand Status

This ledger tracks external discovery surfaces that may retain the former `mcp-video`
name, repository slug, package instructions, description, or feature counts after the
Kinocut 1.7.0 cutover.

## Canonical Listing Data

- Name: **Kinocut**
- Repository: `https://github.com/KyaniteLabs/kinocut`
- Website: `https://kinocut.dev/`
- MCP Registry ID: `io.github.KyaniteLabs/kinocut`
- Python package: `kinocut`
- CLI: `kino`
- Compatibility names: `mcp-video` package/CLI and `mcp_video` import
- Description: Guardrailed video editing for AI agents with FFmpeg, captions,
  effects, Hyperframes, resumable workflows, repurposing, quality gates, and
  provenance receipts.
- Current tool count: 135 MCP tools
- Current release: 1.7.0

## Live Reconciliation

| Surface | State at 2026-07-10 | Required action |
| --- | --- | --- |
| Official MCP Registry | Current and active | Verify after every release |
| Glama | Stale former name, repository slug, install commands, and feature copy | Request canonical recrawl and old-record redirect |
| Awesome MCP Servers | [Correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817) open | Replace the existing multimedia entry; downstream recrawls follow its merge |
| Smithery | No verified canonical Kinocut listing found | Submit canonical repository after upstream listings settle |
| MCP.so | No verified canonical Kinocut listing found | Submit canonical repository |
| Enterprise DNA | Stale downstream record derived from Awesome MCP Servers | Allow upstream correction to propagate, then request recrawl |
| Agent-CoreX | Stale former name and 26-tool description | Request owner refresh |
| Freshcrate | Stale former owner, package, and release | Request repository re-index |
| Remote OpenClaw | Stale former slug and 91-tool copy | Request repository re-index |
| Protodex | Stale former name, 83-tool copy, and obsolete install commands | Request owner refresh |
| Vibehackers | Stale registry ID, package, and release | Request owner refresh |
| Neura Market | Stale personal namespace and 82-tool copy | Request owner refresh |
| a-gnt | Stale personal namespace, old version, and 82-tool copy | Allow Awesome correction to propagate, then request recrawl |
| Docker MCP Catalog | No verified canonical listing found | Submit after catalog requirements are confirmed |
| Claude Connectors Directory | No verified canonical listing found | Pursue verified listing when local stdio servers are eligible |

## Reconciliation Rules

1. Update upstream sources before downstream mirrors.
2. Never delete compatibility package names from install-history documentation; label
   them as compatibility names instead.
3. Do not claim a directory is corrected until its public page shows the canonical
   name, repository, install command, and current capability summary.
4. Record submission and correction URLs in the Forgejo tracking issue.
5. Recheck downstream mirrors after the Awesome MCP Servers change is merged.
