---
name: mcp-video
description: Use mcp-video for guarded video editing, FFmpeg operations, media analysis, subtitles, audio workflows, Hyperframes rendering, repurposing packages, and release checkpoints through an MCP server, Python client, or CLI. Trigger when an agent needs to inspect, edit, render, validate, or package local media safely.
---

# mcp-video

Use mcp-video when an agent needs a structured video-editing surface instead of hand-writing FFmpeg commands. It exposes MCP tools, a Python client, and a CLI for editing, analysis, subtitles, audio, Hyperframes, and local repurposing workflows.

## Start Here

- Read `../../README.md` for installation, agent workflows, and the safety contract.
- Read `../../docs/CLI_REFERENCE.md` for command names and flags.
- Read `../../docs/TOOLS.md` for MCP tool coverage.
- Read `../../docs/PYTHON_CLIENT.md` when scripting multi-step workflows.
- Run `mcp-video doctor` before media work that depends on FFmpeg, Hyperframes, image tools, or AI dependencies.

## Choose A Surface

- MCP: best for Claude Code, Cursor, Codex-style clients, and other agent hosts. Configure `uvx --from mcp-video mcp-video`.
- CLI: best for direct local edits, quick diagnostics, batch jobs, and CI-friendly JSON output.
- Python client: best for repeatable pipelines that need structured results and output paths.

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
mcp-video composite-layers --spec layers.json -o composite.mp4 --save-layer-plan layer-plan.json
mcp-video video-quality-check clip.mp4
mcp-video repurpose-plan clip.mp4 --platforms youtube-shorts instagram-reel tiktok
mcp-video repurpose clip.mp4 --platforms youtube-shorts instagram-reel tiktok
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
