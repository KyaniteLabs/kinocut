---
name: mcp-video
description: Use mcp-video for guarded video editing, source-backed planning, FFmpeg operations, media analysis, subtitles, audio workflows, Hyperframes rendering, repurposing packages, and release checkpoints through an MCP server, Python client, or CLI. Trigger when an agent needs to inspect, plan, edit, render, validate, or package local media safely.
---

# mcp-video

Use mcp-video when an agent needs a structured video-editing surface instead of hand-writing FFmpeg commands. It exposes MCP tools, a Python client, and a CLI for editing, analysis, subtitles, audio, Hyperframes, layered compositing, and local repurposing workflows.

## Start Here

- Read `../../README.md` for installation, agent workflows, and the safety contract.
- Read `../../docs/CLI_REFERENCE.md` for command names and flags.
- Read `../../docs/TOOLS.md` for MCP tool coverage.
- Read `../../docs/PYTHON_CLIENT.md` when scripting multi-step workflows.
- Read `../../docs/WORKFLOWS.md` for the agent workflow engine (job-spec, `@refs`, variants, resume, receipts).
- Read `../../docs/RESCUE.md` for local diagnosis and content-preserving "fix this clip" work.
- Read `../../docs/POST_RESCUE_FEATURES.md` for semantic, visual, restorative, composition, autopilot, and egress planning.
- Run `mcp-video doctor` before media work that depends on FFmpeg, Hyperframes, image tools, or AI dependencies.

## Choose A Surface

- MCP: best for Claude Code, Cursor, Codex-style clients, and other agent hosts. Configure `uvx --from mcp-video mcp-video`.
- CLI: best for direct local edits, quick diagnostics, `composite-layers --dry-run`, batch jobs, and CI-friendly JSON output.
- Python client: best for repeatable pipelines that need structured results, output paths, and saved layer-plan receipts.

## Dedicated Video Rescue

Use `video_rescue_*`, `rescue-*`, or `Client.rescue_*` when the request is to fix one local
clip while preserving its source, story, and timeline.

Required sequence:

1. Call plan and save the plan artifact.
2. Present `safe_repairs`, `recommendations`, `unavailable_repairs`, `blocked_repairs`,
   previews, package intents, capabilities, and estimate to the user.
3. Inspect the plan before render. Obtain or infer explicit approval only for IDs in
   `safe_repairs`; omitting the ID list means all safe IDs in the reviewed plan.
4. Call render with exactly those approved safe IDs.
5. Inspect the render receipt, then report package paths, unavailable sidecars, integrity,
   gating verification, privacy, resume, and cleanup state.

Never render directly from an unreviewed plan. Never add recommendation IDs, unavailable
IDs, or blocked IDs to approval. Never use cloud tools, burn rescue captions, rewrite the
source, or treat `unavailable` as automatic failure. A cancellation or verification failure
must remain unpromoted or quarantined.

## Post-Rescue Planning

Use the matching `video_*` MCP tool, flat CLI command, or `Client` method when the request
needs semantic retrieval, ordinary cleanup edits, subject-aware transforms, restoration,
composition, creative coordination, or remote egress. Pass JSON-compatible evidence and
intent; present the returned plan and diff before any separate render step.

Never invent source descriptions, hide uncertainty, infer approval from a plan, or treat a
missing local executor as permission to use a cloud provider. Remote work requires a separate
egress manifest and approval. A planner that lacks evidence or capability must abstain.

## Layered Compositing

Use `composite-layers` / `video_composite_layers` when the edit is an ordered stack of image, video, or solid layers, especially lower thirds, picture-in-picture variants, blurback plates, masks/mattes, or platform-specific layout variants.

Prefer this path over raw FFmpeg filtergraphs when an agent needs transforms, opacity, start/duration windows, mask/matte alpha sources, or a receipt that can be reviewed before publishing.

Plan-first flow:

1. Write a JSON spec with `canvas`, ordered `layers`, and explicit output.
2. Run `mcp-video composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json`.
3. Inspect the layer plan for source hashes, filtergraph hash, transforms, rotation/pivot, blend modes, timing windows, and masks.
4. Render only after the plan looks right.
5. Run `video-quality-check`, `storyboard` or `thumbnail`, and `video_release_checkpoint`.

The compositor now also supports **full-canvas** blend modes (`multiply`, `screen`, `overlay`, `darken`, `lighten`) and **rotation** with a new `pivot` reference point; the `layer_plan` receipt is v2. A non-`normal` blend layer must be full-canvas (else `unsupported_blend_geometry`), output is video-only, and the existing `anchor` stays a position alias distinct from `pivot`. Still deferred and fail-closed: positioned/scaled/masked/timed blend, rotation + mask, per-layer effect routing, audio compositing, and full NLE adapters. Do not use `composite-layers` as a full NLE replacement.

## Agent Workflow Engine

When the edit is a multi-step job (not a single tool call), use the workflow engine to plan, validate, render, recover, and prove it from one JSON job-spec — through `video_workflow_*` (MCP), `workflow-*` (CLI), or `Client.workflow_*` (Python). Ops are a small allowlist (`probe | trim | resize | convert | merge | add_text`) mapped 1:1 to vetted engines; media references are symbolic (`@sources.*`, `@work/*`, `@outputs.*`) and workspace-confined; everything fails closed. See `../../docs/WORKFLOWS.md`.

Plan → validate → render → inspect → resume:

1. `workflow-validate --spec job.json` — cheap structural gate; renders nothing.
2. `workflow-plan --spec job.json --save-plan plan.json` — dry-run op graph + source probes/hashes; renders zero media.
3. `workflow-render --spec job.json --save-receipt receipt.json` — execute sequentially; emit a provenance receipt (per-step hashes, cleanup manifest, determinism caveat). Add `--all-variants` for batch variants.
4. `workflow-inspect --receipt receipt.json` — read-only integrity re-check + human-review pointers before trusting a receipt.
5. `workflow-render --spec job.json --resume receipt.json` — resume a job that failed with intermediates kept (fail-closed on a changed spec).

Receipts store workspace-relative paths only — keep specs and example receipts free of home paths, usernames, and tokens.

## Workflow

1. Inspect the input first: `mcp-video info <file>` or the MCP/Python equivalent.
2. Make a low-risk plan: trim, resize, normalize audio, subtitles, overlays, effects, or Hyperframes render.
3. Prefer previews or dry-run manifests before expensive or destructive exports:
   - `preview` for quick visual review.
   - `repurpose-plan` before `repurpose`.
   - Hyperframes `inspect`, `snapshot`, or `still` before full render.
4. Produce release artifacts before publishing:
   - `video-quality-check`
   - `storyboard` or `thumbnail`
   - `video_release_checkpoint` through MCP or `Client.release_checkpoint()` through Python
5. Ask for human visual/audio review before treating generated media as final.

## CLI Examples

```bash
mcp-video doctor
mcp-video --format json info interview.mp4
mcp-video trim interview.mp4 -s 00:02:15 -d 45
mcp-video video-ai-transcribe clip.mp4 --output captions.srt
mcp-video subtitles clip.mp4 captions.srt
mcp-video resize clip.mp4 --aspect-ratio 9:16
mcp-video composite-layers --spec layers.json --dry-run --save-layer-plan layer-plan.json
mcp-video composite-layers --spec layers.json -o composite.mp4 --save-layer-plan layer-plan.json
mcp-video video-quality-check clip.mp4
mcp-video repurpose-plan clip.mp4 --platforms youtube-shorts instagram-reel tiktok
mcp-video repurpose clip.mp4 --platforms youtube-shorts instagram-reel tiktok
```

## Python Example

```python
from mcp_video import Client

video = Client()
plan = video.composite_layers(
    "layers.json",
    output="composite.mp4",
    save_layer_plan="layer-plan.json",
    dry_run=True,
)
```

## MCP Setup

```json
{
  "mcpServers": {
    "mcp-video": {
      "command": "uvx",
      "args": ["--from", "mcp-video", "mcp-video"]
    }
  }
}
```

## Guardrails

- Do not publish or hand off media without a quality check and human review.
- Prefer structured mcp-video tools over raw FFmpeg shell commands; use `composite-layers`/`video_composite_layers` for ordered layer stacks instead of hand-written filtergraphs.
- Keep output paths explicit so generated media is easy to inspect.
- For Hyperframes, verify project structure and rendered snapshots before full video export.
