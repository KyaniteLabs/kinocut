# Kinocut documentation

Start with the [project README](../README.md). This page maps the rest. Everything under
**Current Guidance** describes how Kinocut works today; the sections after it are dated
records.

Kinocut was called `mcp-video` until 2026-07-10. Historical records keep the names,
versions and commands they actually verified.

## Current Guidance

**Start here**

- [Install matrix](INSTALL.md) - FFmpeg, Python, extras and host setup.
- [Golden path](GOLDEN_PATH.md) - a first run that ends in a checked clip and a receipt.
- [Integrations](INTEGRATIONS.md) - Claude Code, Claude Desktop, Cursor, Gemini CLI and other MCP clients.
- [FAQ](faq.md)
- [Good first agent tasks](first-agent-tasks.md)

**Reference**

- [MCP tools](TOOLS.md) - every tool by name.
- [MCP operation families](MCP_TOOL_FAMILIES.md) - the default surface: hot path, families, `list_operations`, `describe_operation`.
- [Tool surface baseline](MCP_TOOL_SURFACE_BASELINE.md) - measured tool counts and listing sizes per mode.
- [Python client](PYTHON_CLIENT.md) - `from kinocut import Client`.
- [CLI reference](CLI_REFERENCE.md) - `kino` commands and flags.
- [Video Receipts](VIDEO_RECEIPT.md) - receipt kinds and what they prove.
- [Public claims](public_claims.json) - published version, counts, registry id and canonical URLs.
- [Agent discovery](AI_AGENT_DISCOVERY.md) and the [extended agent guide](llms-full.txt).

**Guides**

- [Agent workflows](WORKFLOWS.md) - JSON job specs, render receipts, resume and cleanup.
- [Podcast to Shorts tutorial](TUTORIAL_PODCAST_TO_SHORTS.md) and [stream shorts](STREAM_SHORTS.md).
- [Video rescue](RESCUE.md) - review-first repair.
- [AI-video review and salvage](AI_VIDEO_REVIEW_AND_SALVAGE.md), [inspection](AI_VIDEO_INSPECTION.md) and [contracts](AI_VIDEO_CONTRACTS.md).
- [360 dual-cam assembly](360_ASSEMBLY.md) - stitched equirectangular MP4 to propose, approve and render.
- [Product / object matte](PRODUCT_MATTE.md) - product and catalog cutouts with `hyperframes-remove-background --model birefnet-general`, available in published 2.0.0 as the optional `kinocut[object-matte]==2.0.0` extra (first shipped in 1.15.1). No new MCP tool. Example: [examples/product-matte/](../examples/product-matte/).
- [Still plates](STILL_PLATES.md) - match and grade a set of stills to a hero image.
- [Audio mixing](AUDIO_MIXING.md) and the sound request guides ([mix](SOUND_MIX_REQUESTS.md), [loudness](SOUND_LOUDNESS_REQUESTS.md), [master](SOUND_MASTER_REQUESTS.md), [caption speech](SOUND_DUB_REQUESTS.md)).
- [Quality evidence](QUALITY_EVIDENCE.md) - what is measured, what is unavailable, what is not evaluated.
- [C2PA provenance](C2PA_PROVENANCE.md) - signed manifests on final exports.
- [Vision and network controls](VISION_PRIVACY.md)
- [Project store lifecycle](PROJECTSTORE_LIFECYCLE.md) - CAS repair, stop requests and resumable jobs.
- [Desktop extension (MCPB)](MCPB.md)
- [Prompt library](PROMPTS.md) and [failure examples](FAILURE_EXAMPLES.md).

**Project**

- [Kinocut now](status/NOW.md) - published release versus development tip, open human gates.
- [Human gates](HUMAN_GATES.md) - what only a person can approve.
- [Roadmap](../ROADMAP.md)
- [Changelog](../CHANGELOG.md)
- [Testing](TESTING.md), [design standards](DESIGN_STANDARDS.md), [platform parity](PLATFORM_PARITY.md)
- [Release ritual](RELEASE_RITUAL.md) and [fleet upgrade](FLEET_UPGRADE.md)
- [Licensing notes](LEGAL_REVIEW.md)
- [Rename story](RENAME.md), [compare](COMPARE.md), [when to recommend](RECOMMEND.md), [enterprise notes](ENTERPRISE.md)
- [Directory status](DIRECTORY_STATUS.md)

## Historical records

- `docs/status/` entries are snapshots: dated release notes, program status and
  closeouts. [NOW.md](status/NOW.md) is the one current status file. The
  [post-campaign tip status](status/2026-07-27-post-campaign-tip-status.md) and the
  post-1.8 and post-1.10 program status files are kept as dated snapshots.
- [docs/archive/](archive/README.md) holds pre-2.0 audits, roadmaps and checklists.
- `docs/proofs/` holds dated release and confidence receipts, such as the
  [1.8.0 release packet](proofs/release-1.8.0/RELEASE_PACKET.md).
- `docs/plans/`, `docs/research/`, `docs/adr/` and `docs/internal/` are dated design
  and research records, not install or usage instructions.
- `CHANGELOG.md` keeps former package names on purpose.

## Compatibility names

The `mcp-video` distribution and CLI, the `mcp_video` import, legacy receipt keys,
`mcp_video_` intermediate prefixes and `mcp-video://` resource aliases still work. New
integrations should use `kinocut`, `kino`, `from kinocut import Client` and `kinocut://`.
