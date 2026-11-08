# Kinocut

A guardrailed local video-production surface for AI agents and humans: probe media, choose typed edits/plans, render with FFmpeg or optional engines, inspect receipts/quality, then obtain human release approval. It is a Python MCP server/library and `kino` CLI, not a hosted editor or automatic permission to publish.

## Existing surfaces

- Typed FFmpeg editing/audio/compositing/caption operations, metadata probes, timeline/workflow/repurposing and quality/release paths.
- Compact default MCP discovery plus typed operation families and searchable/profile-selected tools. Actual default discovery returned 30 tools; README's full-catalog/published-release counts describe a different surface and must not be substituted for that number.
- Optional Hyperframes/Revideo, transcription/stem/upscale and image/sound/AI-video/review integrations. Dependencies/providers/models are capability-specific, not included or accepted merely because the base package installs.
- Video Receipt/provenance, explicit overwrite consent, source/output checks and human review gates. Planning, rendering, acceptance and publication remain distinct operations.
- Templates, QA fixtures/golden packs and workflow specs support development; they are not rights-cleared user footage, a quality guarantee or current benchmark certification.

## Docs proof and limits

Isolated base install and actual CLI help passed. `kino info` probed a new one-second synthetic 320×180 H.264 clip correctly; a pure time parser assertion and actual default MCP discovery passed. No existing footage/profile was touched, no cleanup/overwrite/render suite ran, no optional model/inference/download or publish/release decision occurred. The synthetic source is a probe fixture, not operator-side editing or creative-quality acceptance.

Runtime source declares 1.16.5; current registry/publication status was not independently revalidated. GitHub is described here by the checkout's README as canonical; do not apply the website repository's opposite mirror policy to this code repo. See [ARCHITECTURE.md](ARCHITECTURE.md), [README.md](README.md) and [domain vocabulary](CONTEXT.md).
