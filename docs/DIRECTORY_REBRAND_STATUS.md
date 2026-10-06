# Directory Rebrand Status

This ledger records external discovery surfaces that may retain the former `mcp-video`
name, repository slug, package instructions, description, or feature counts after the
Kinocut rename. The reconciliation table is a 2026-07-10 snapshot, not a live claim
about third-party pages; verify an external page before acting on its listed state.

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
- Published surface: 203 MCP tools / 177 CLI commands (1.16.1)
- Development tip: 203 MCP tools / 177 CLI commands (matches the published release at cutover; future local changes remain Unreleased)
- Current release: 1.16.1 (published 2026-10-05)
- Provider check (2026-10-05): PyPI/npm and GitHub release publicly report 1.16.1; the initial publication gate read official MCP Registry 1.16.1, but later reads timed out. Shim 1.6.16 pins 1.16.1. The last verified live site remains 1.16.0; 1.16.1 website source is prepared but not deployed. Immutable PyPI descriptions retain dated earlier checkpoints; current source guidance is updated without claiming vendor acceptance.
- Submission ops: `docs/status/DIRECTORY_SUBMISSION_OPS.md`

## Reconciliation Snapshot (2026-07-10)

Current follow-up (2026-10-05): [Glama](https://glama.ai/mcp/servers/KyaniteLabs/kinocut) still displays the legacy `pastorsimon1798/mcp-video` identity. [Awesome MCP Servers PR #15050](https://github.com/punkpeye/awesome-mcp-servers/pull/15050) remains open and conflicted, with stale 201-tool / 1.15.2 copy. Its maintainer bot requests passing Glama introspection and a Glama badge. Branch/count corrections can proceed while Glama resolves the identity; external listing acceptance still depends on the vendor checks and maintainer review. The older merged PR below is not evidence that this later update merged.

Fresh submission metadata on 2026-10-05 confirms [MCP.so #3098](https://github.com/chatmcp/mcpso/issues/3098), [Agent-CoreX #2](https://github.com/ankitpro/agent-corex/issues/2), [Protodex #26](https://github.com/LuciferForge/mcp-directory/issues/26) and [Docker catalog PR #4387](https://github.com/docker/mcp-registry/pull/4387) remain open. The first three retain historical 135-tool submissions (Agent-CoreX and Protodex also name 1.7.0). Docker's current head `ebb0b0966303a58b9b57916175220f6ebf778e38` pins v1.15.1 source `b2498333acc8c0e29cba7e6ceca19603cc8bedaf`; its local verification report is not 1.16.0 catalog acceptance. That head has no posted check runs or commit statuses; an empty pending rollup is not evidence of an executing job. External maintainer acceptance and the resulting public listing remain separate from submission preparation. Confirm the accepted pin with the existing owner before changing the Docker submission.

| Surface | State at 2026-07-10 | Required action |
| --- | --- | --- |
| Official MCP Registry | Current and active | Verify after every release |
| Glama | Canonical URL and score badge resolve, but the page displays stale former metadata | Refresh and redirect request sent to Glama support on 2026-07-10; await recrawl |
| Awesome MCP Servers | [Correction PR #9817](https://github.com/punkpeye/awesome-mcp-servers/pull/9817) **merged 2026-08-08** | Downstream mirrors should propagate; recheck Glama and others after recrawl |
| Smithery | No canonical listing; the truthful staged MCPB foundation merged in PR #124 but is not self-contained | Complete and verify native runtime issue #125 before submitting; do not publish the staged launcher |
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
- MCPB: staged packaging foundation merged in Forgejo PR #124; self-contained native
  runtime work and its release blockers are tracked in issue #125. No Smithery
  submission is claimed.

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
