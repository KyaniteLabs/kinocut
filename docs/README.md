# Kinocut Documentation Map

Use this page to distinguish current operating guidance from dated evidence. The
project was renamed from `mcp-video` to **Kinocut** on 2026-07-10; historical
artifacts keep the names, versions, commands, and paths they actually verified.

## Current Guidance

- [CLI reference](CLI_REFERENCE.md) - canonical `kino` commands and flags.
- [MCP tools](TOOLS.md) - public tool categories and contracts.
- [Python client](PYTHON_CLIENT.md) - canonical `from kinocut import Client` usage.
- [Agent workflows](WORKFLOWS.md) - job specs, render receipts, resume, and cleanup.
- [Video rescue](RESCUE.md) - review-first repair pipeline.
- [Testing](TESTING.md) - focused, integration, and real-media verification.
- [Design standards](DESIGN_STANDARDS.md) - visual metrics, units, and guardrails.
- [Licensing notes](LEGAL_REVIEW.md) - project and dependency obligations.
- [Agent discovery](AI_AGENT_DISCOVERY.md) - concise capability and setup summary.

## Strategy And Roadmap

- [Product roadmap](../ROADMAP.md) - shipped and pending product work.
- [Trusted execution layer plan](plans/2026-07-09-kinocut-trusted-execution-layer.md) - approved phased plan and live Phase 0 status.
- [Kinocut research pack](plans/kinocut-research/README.md) - dated evidence behind the approved plan.
- [Integration roadmap](INTEGRATION-ROADMAP.md) - completed and deferred integrations.
- [Feature roadmap](KINOCUT-FEATURES-ROADMAP.md) - detailed feature history and backlog.
- [Audio feature design](KINOCUT-AUDIO-FEATURES.md) - procedural-audio design record.

## Historical Evidence

- `docs/proofs/` contains dated release and confidence receipts.
- Dated audits, handoffs, plans, and `docs/internal/` research are snapshots, not
  current install or source-layout instructions.
- `CHANGELOG.md` is intentionally historical and retains former package names.

## Compatibility Names

The `mcp-video` distribution, `mcp-video` CLI, `mcp_video` import, legacy receipt
keys, `mcp_video_` intermediate prefixes, and `mcp-video://` resource aliases are
preserved compatibility contracts. New integrations should use `kinocut`, `kino`,
`from kinocut import Client`, and `kinocut://` for new resources.
