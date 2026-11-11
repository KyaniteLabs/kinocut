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
  **How to reach them:** neither is listed by name on the default 18 tools.
  On the default surface, call them through the `video_plan_ops` family as
  `{"operation": "video_repurpose_plan", "params": {...}}`; `describe_operation`
  returns each one's parameters. To list them by name instead, start the server
  with `KINOCUT_TOOLS=profile:editor` (or `all`) and restart it after changing
  the variable. If neither `video_plan_ops` nor the named tools are available,
  stop and report that the repurpose tools are unavailable instead of retrying.
  The mapping is explicit:
  `profile:editor` carries `video_repurpose_plan`, `video_repurpose`;
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
   `repurpose_plan.json` for platform outputs, aspect ratios, target LUFS, max
   duration, and planned review artifacts.
4. Render with `repurpose` / `video_repurpose` only after the plan is plausible.
5. Inspect the rendered manifest, thumbnails, storyboards, and release checkpoint output.
6. Stop at human review. Do not publish, schedule, upload, or claim final approval.

### Rendering over MCP is a submitted job

The CLI `repurpose` renders before it returns. The MCP `video_repurpose` does not:
it submits one durable render job and returns at once with `job_id`, `status`
(usually `queued` or `running`) and a `clips` list. A successful call means the job
was accepted, not that any clip exists yet or passed review.

- **Paths are project-relative.** Each clip's `output` and `receipt_ref` are relative
  to the project folder: the `output_dir` you passed, or the auto-created
  `repurpose-project` folder next to the source when you passed none. Join them to
  that folder before reading a file.
- **Progress lives in the receipt.** The worker rewrites `<project>/<receipt_ref>`
  after each finished stage; each entry in its `steps` list has a `status`. Treat a
  clip as ready only when its file exists and every step reads `completed`. Do not
  inspect, quote or hand off a clip path before that.
- **No status tool to poll.** There is no MCP tool for job status. If a step did not
  complete, or the receipt is missing or stops changing, say so and report the
  `job_id`; do not resubmit the job to "retry", which renders a second copy.
- **Human review still gates handoff.** A finished job is rendered output, not
  approved output. Steps 5 and 6 apply unchanged.

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
