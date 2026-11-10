# Kinocut

A guardrailed local video-production surface for AI agents and humans: probe media, choose typed edits/plans, render with FFmpeg or optional engines, inspect receipts/quality, then obtain human release approval. It is a Python MCP server/library and `kino` CLI, not a hosted editor or automatic permission to publish.

## Existing surfaces

- Typed FFmpeg editing/audio/compositing/caption operations, metadata probes, timeline/workflow/repurposing and quality/release paths.
- Compact default MCP discovery plus typed operation families and searchable/profile-selected tools. Actual default discovery returns 18 tools (8-tool hot path + family layer); README's full-catalog/published-release counts describe a different surface and must not be substituted for that number.
- Optional Hyperframes/Revideo, transcription/stem/upscale and image/sound/AI-video/review integrations. Dependencies/providers/models are capability-specific, not included or accepted merely because the base package installs.
- Video Receipt/provenance, explicit overwrite consent, source/output checks and human review gates. Planning, rendering, acceptance and publication remain distinct operations.
- Templates, QA fixtures/golden packs and workflow specs support development; they are not rights-cleared user footage, a quality guarantee or current benchmark certification.

## See also

[ARCHITECTURE.md](ARCHITECTURE.md), [README.md](README.md) and the [domain vocabulary](CONTEXT.md).
