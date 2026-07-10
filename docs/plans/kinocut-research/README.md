# Kinocut research pack (2026-07-09/10)

Source material behind the approved master plan
(`../2026-07-09-kinocut-trusted-execution-layer.md`) and the gated backlog
(epic #85, issues #54-#107). Read the plan first; come here when an issue
references research evidence or the kernel API contracts.

| File | What it is |
|---|---|
| 00-roadmap-synthesis.md | The 9-lane synthesis: identity thesis, three Tier-1 bets, distribution playbook, traps |
| 01-architecture-audit-api-contracts.md | **In-repo architecture audit + the kernel primitive API sketches referenced by P1.x issues as "the contract"** |
| 02-competitive-landscape.md | ~40 video MCPs mapped; who has what; features nobody nailed |
| 03-frontier-agentic-video.md | Gen-video APIs, VLM review loops, semantic editing, MCP Tasks/OTIO/C2PA clocks |
| 04-demand-jtbd.md | Creator/agency demand evidence; top-10 jobs-to-be-done ranking cited by P2.x issues |
| 05-distribution-mechanics.md | How comparable tools blew up; the moment playbook behind Track D |
| 06-red-team-bear-case.md | Why this could fail + neutralizers (source of the intent-verb + repurposing-as-product decisions) |
| 07-futurist-2027.md | The "Nix/Docker for video" thesis; trap list (what we deliberately do NOT build) |
| 08-wedge-features-positioning.md | Wedge feature sketches; audience decision (AI-app builders first) |

Provenance: 4 Claude web-research agents + codex (in-repo) + kimi + glm + agy
lanes, orchestrated 2026-07-09; plan approved by Simon 2026-07-10 after a
3-round Planner/Architect/Critic consensus loop (revision history in the plan).

## Snapshot note

This pack was captured immediately before the rename, when the project was still
called `mcp-video` and exposed 119 tools. Those names, counts, stars, and market
observations are retained where they are evidence from that dated snapshot. Current
implementation guidance uses **Kinocut**, the `kinocut/` package, `kino` CLI, and
`kinocut://` resources. The verified release-cutover surface is **135 MCP tools and
114 CLI commands**; re-check live market statistics before quoting them externally.
