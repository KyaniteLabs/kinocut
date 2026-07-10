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
| Glama | Stale former name, repository slug, install commands, and feature copy | Owner-authenticated canonical submission and old-record redirect still required |
| Awesome MCP Servers | [Correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817) open; checks pass | Complete Glama prerequisite, restore its score badge, and merge the replacement entry |
| Smithery | No canonical listing; local stdio submission currently requires an MCPB bundle | Add MCPB packaging before submitting; do not publish an incompatible listing |
| MCP.so | [Submission issue #3098](https://github.com/chatmcp/mcpso/issues/3098) open | Await directory review and verify the published record |
| Enterprise DNA | Stale downstream record derived from Awesome MCP Servers | Allow upstream correction to propagate, then request recrawl |
| Agent-CoreX | Stale former name and 26-tool description | Request owner refresh |
| Freshcrate | Stale former owner, package, and release | Request repository re-index |
| Remote OpenClaw | Stale former slug and 91-tool copy | Request repository re-index |
| Protodex | Stale former name, 83-tool copy, and obsolete install commands | Request owner refresh |
| Vibehackers | Stale registry ID, package, and release | Request owner refresh |
| Neura Market | Stale personal namespace and 82-tool copy | Request owner refresh |
| a-gnt | Stale personal namespace, old version, and 82-tool copy | Allow Awesome correction to propagate, then request recrawl |
| Docker MCP Catalog | [Catalog PR #4387](https://github.com/docker/mcp-registry/pull/4387) open | Await registry build, security review, and maintainer approval |
| Claude Connectors Directory | No verified canonical listing found | Pursue verified listing when local stdio servers are eligible |

## Submission Receipts

- GitHub mirror smoke: [run 29126013541](https://github.com/KyaniteLabs/kinocut/actions/runs/29126013541)
- GitHub mirror protection: ruleset `Protect mirrored master history` blocks branch
  deletion and non-fast-forward updates while preserving normal Forgejo mirror pushes.
- Awesome MCP Servers: [correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817)
- MCP.so: [submission issue #3098](https://github.com/chatmcp/mcpso/issues/3098)
- Docker MCP Registry: [catalog PR #4387](https://github.com/docker/mcp-registry/pull/4387)

Glama's public flow requires owner authentication and human verification. The
canonical repository already contains `glama.json` with the maintainer identity and
a Dockerfile, so no source change is needed before completing that flow.

## Reconciliation Rules

1. Update upstream sources before downstream mirrors.
2. Never delete compatibility package names from install-history documentation; label
   them as compatibility names instead.
3. Do not claim a directory is corrected until its public page shows the canonical
   name, repository, install command, and current capability summary.
4. Record submission and correction URLs in the Forgejo tracking issue.
5. Recheck downstream mirrors after the Awesome MCP Servers change is merged.
