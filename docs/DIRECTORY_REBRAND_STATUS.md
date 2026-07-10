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
| Glama | Canonical URL and score badge resolve, but the page displays stale former metadata | Refresh and redirect request sent to Glama support on 2026-07-10; await recrawl |
| Awesome MCP Servers | [Correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817) open; checks pass | Complete Glama prerequisite, restore its score badge, and merge the replacement entry |
| Smithery | No canonical listing; local stdio submission currently requires an MCPB bundle | Add MCPB packaging before submitting; do not publish an incompatible listing |
| MCP.so | [Submission issue #3098](https://github.com/chatmcp/mcpso/issues/3098) open | Await directory review and verify the published record |
| Vidocu video MCP roundup | Current article omits Kinocut | Outreach sent to the publisher on 2026-07-10; await editorial response |
| ffpipe roundup | No matching public roundup was found; ffpipe's live site currently promotes its own MCP service | Recheck only if a roundup URL is supplied or published |
| Enterprise DNA | Stale downstream record derived from Awesome MCP Servers | Allow upstream correction to propagate, then request recrawl |
| Agent-CoreX | [Refresh issue #2](https://github.com/ankitpro/agent-corex/issues/2) open for the stale former name and 26-tool description | Await owner refresh and verify the public page |
| Freshcrate | Stale former owner, package, and release; correction form is currently unconfigured | Retry when its contact inbox is operational or an owner channel is published |
| Remote OpenClaw | Stale former slug and 91-tool copy | Refresh request sent to the publisher on 2026-07-10; await re-index |
| Protodex | [Refresh issue #26](https://github.com/LuciferForge/mcp-directory/issues/26) open for the stale former name, 83-tool copy, and obsolete install commands | Await weekly re-index and verify the redirect |
| Vibehackers | Stale registry ID, package, and release | Refresh request sent to the publisher on 2026-07-10; await re-index |
| Neura Market | Stale personal namespace and 82-tool copy | Refresh request sent to the publisher on 2026-07-10; await re-index |
| a-gnt | Stale personal namespace, old version, and 82-tool copy | Allow Awesome correction to propagate, then request recrawl |
| Docker MCP Catalog | [Catalog PR #4387](https://github.com/docker/mcp-registry/pull/4387) open | Await registry build, security review, and maintainer approval |
| Claude Connectors Directory | No verified canonical listing found | Pursue verified listing when local stdio servers are eligible |

## Submission Receipts

- GitHub mirror smoke: [run 29126013541](https://github.com/KyaniteLabs/kinocut/actions/runs/29126013541)
- GitHub mirror protection: ruleset `Protect mirrored master history` blocks branch
  deletion and non-fast-forward updates while preserving normal Forgejo mirror pushes.
- Awesome MCP Servers: [correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817)
- MCP.so: [submission issue #3098](https://github.com/chatmcp/mcpso/issues/3098)
- MCP.Directory: canonical repository and PyPI package submitted for review on
  2026-07-10; the form confirmed publication review within 24 hours.
- Vidocu: editorial inclusion request sent to the article publisher on 2026-07-10.
- Remote OpenClaw, Vibehackers, and Neura Market: canonical refresh requests sent
  to their published contact channels on 2026-07-10.
- Docker MCP Registry: [catalog PR #4387](https://github.com/docker/mcp-registry/pull/4387)
- Agent-CoreX: [refresh issue #2](https://github.com/ankitpro/agent-corex/issues/2)
- Protodex: [refresh issue #26](https://github.com/LuciferForge/mcp-directory/issues/26)
- Freshcrate: correction form attempted on 2026-07-10, but the site reported that
  its contact inbox was not configured; no successful submission is claimed.

Glama's public flow requires owner authentication and human verification. The
canonical repository already contains `glama.json` with the maintainer identity and
a Dockerfile, and a support request was sent on 2026-07-10, so no source change is
needed while the recrawl is pending.

## Reconciliation Rules

1. Update upstream sources before downstream mirrors.
2. Never delete compatibility package names from install-history documentation; label
   them as compatibility names instead.
3. Do not claim a directory is corrected until its public page shows the canonical
   name, repository, install command, and current capability summary.
4. Record submission and correction URLs in the Forgejo tracking issue.
5. Recheck downstream mirrors after the Awesome MCP Servers change is merged.
