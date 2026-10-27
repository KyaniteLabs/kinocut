---
name: kinocut-repurpose
description: Use when turning one local video into a platform-ready short. Kinocut builds clip packages with manifests, review artifacts, and human approval gates.
---

# Kinocut Repurpose

This is a pre-kernel, path-based v1 skill. It guides an agent to produce a good short
clip from one local video using only shipped Kinocut tools. Do not invent commands,
providers, kernels, schedulers, uploaders, or publishing steps.

## Plugin runtime

The host starts the pinned Kinocut server from this plugin's `mcp.json`.
Use its MCP tools directly. Do not install another copy, copy skills into
another host, or change another tool's configuration. CLI examples below apply
only when `kino` is already available; otherwise use the equivalent MCP tools.

## Current Tools

Use these shipped surfaces only:

- MCP: `video_repurpose_plan`, then `video_repurpose`.
  **Prerequisite:** both are profile tools, not part of the default 20-tool
  core. Start the server with `KINOCUT_TOOLS=profile:editor` (or `all`) and
  restart it after changing the variable; `search_tools` finds their names but
  does not register them. On the default surface, stop and report that the
  repurpose tools are unavailable instead of retrying.
- CLI: `repurpose-plan`, then `repurpose`.
- Optional support tools when needed: `info`, `video-ai-transcribe`, `generate-subtitles`,
  `subtitles`, `resize`, `normalize-audio`, `thumbnail`, `storyboard`,
  `video-quality-check`.

Useful CLI shape:

```bash
kino --format json info input.mp4
kino repurpose-plan input.mp4 --platforms youtube-shorts instagram-reel tiktok -o repurpose-out
kino repurpose input.mp4 --platforms youtube-shorts instagram-reel tiktok -o repurpose-out --min-score 0
kino video-quality-check repurpose-out/youtube_shorts.mp4
```

## Required Flow

1. Inspect the source path first with `info` or `video_info`. Confirm duration,
   resolution, aspect, and audio presence.
2. Choose one short-clip intent and two or three platforms. Prefer
   `youtube-shorts`, `instagram-reel`, and `tiktok` for vertical clips unless the user
   explicitly asks for horizontal or square.
3. Run `repurpose-plan` / `video_repurpose_plan` before rendering. Review the
   `repurpose_manifest.json` for platform outputs, aspect ratios, target LUFS, max
   duration, and planned review artifacts.
4. Render with `repurpose` / `video_repurpose` only after the plan is plausible.
5. Inspect the rendered manifest, thumbnails, storyboards, and release checkpoint output.
6. Stop at human review. Do not publish, schedule, upload, or claim final approval.

## Guardrails

- Captions: if speech matters and captions are missing, create or request an SRT before
  final review. Use `video-ai-transcribe` only when the host has the optional dependency;
  otherwise ask for a transcript or use `generate-subtitles` from provided text. Burn
  captions with `subtitles` only when the user wants burned-in captions.
- Audio: preserve voice intelligibility. Use `normalize-audio` or the repurpose tool's
  target LUFS defaults. Re-check clips that sound clipped, silent, or out of sync.
- Aspect: respect each platform manifest. Vertical short clips are `9:16`; square posts
  are `1:1`; YouTube landscape is `16:9`. Do not crop important faces or text blindly.
- Pacing: keep the clip short and legible. If the source is too long for the selected
  platform, trim first with the existing `trim` command, then repurpose the trimmed path.
- Output review: require a manifest, thumbnail, storyboard, quality check, and release
  checkpoint artifact before handoff. Human review is mandatory before public use.
- Local-only: keep paths explicit and local. Do not download, upload, post, publish, or
  call cloud services unless the user separately asks and approves that external step.

## Deterministic Demo

Run the bundled demo recipe from the repository root:

```bash
python examples/repurpose_current_tools_demo.py --output-dir /tmp/kinocut-repurpose-demo
```

Dry-run the exact recipe without rendering:

```bash
python examples/repurpose_current_tools_demo.py --dry-run
```

The script creates a deterministic FFmpeg fixture, runs `repurpose-plan`, renders
`youtube-shorts` and `instagram-reel` variants with current Kinocut CLI commands, then
checks the manifest and review artifacts.
