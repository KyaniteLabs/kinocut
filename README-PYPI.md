<!-- mcp-name: tech.kyanitelabs/kinocut -->

# Kinocut

Your agent edits the video. You approve the cut.

Kinocut is a local, guardrailed video-editing MCP server, Python client and `kino`
CLI built on FFmpeg. Every edit is checked before FFmpeg runs, writes a new file
unless you allow an overwrite, and returns a structured result. Quality gates catch
black frames, silence and bad loudness, and a Video Receipt records what ran.
Formerly mcp-video.

## What your agent sees

By default the MCP server lists 18 tools: an 8-tool hot path (`video_info`,
`video_trim`, `video_merge`, `video_add_text`, `video_add_audio`,
`video_extract_frame`, `video_shorts`, `video_doctor`), eight operation families
that reach every other operation, and `list_operations` / `describe_operation`
to find and fetch them. `KINOCUT_TOOLS=profile:<name>` lists one job's tools by
name and `KINOCUT_TOOLS=all` lists all 206.

`video_review_card` turns a finished cut into a review card with a contact sheet
and Approve, Dig in and Try another range buttons for Hermes Desktop chat.

## Install and inspect

Requires Python 3.11 or newer, plus FFmpeg and ffprobe on `PATH`.

```bash
pip install kinocut==2.0.0
kino doctor
kino info input.mp4
```

Agent plugins launch a specific published version through uv. Follow the
[plugin instructions](https://github.com/KyaniteLabs/kinocut/tree/master/plugins/kinocut)
for the host you use. Kinocut also provides `from kinocut import Client`; the
older `mcp_video` import remains supported.

## Output safety

Prefer new output paths. Replacing an existing output requires explicit
`overwrite=true` (CLI `--overwrite`). Existing non-media artifacts also require
evidence that the same durable job created them. Agent configuration homes are
protected. Use one writer per output, check the result, and require human
visual/audio review before publishing.

## Optional model calls and network use

Ordinary local FFmpeg editing and color grading need no account, model SDK or
API key. Kinocut's optional vision calls default to `KINOCUT_VISION_MODE=off`.
For observations with your chosen provider, prepare local images through
Kinocut and inspect them with the host agent's image tools, including local
models. Kinocut does not automatically inherit the host's model configuration.

Kinocut's own optional product-description adapter requires an
Anthropic-compatible endpoint and explicit local or remote configuration.
The separate sampled-frame Anthropic QC path also requires explicit remote
permission and configuration. A local/custom product route cannot activate it.

Installing packages downloads dependencies. URL inputs download requested media;
font and model-weight features may fetch assets from GitHub. Explicit Revideo
installation runs `npm ci` and may download renderer/browser dependencies.
Revideo telemetry defaults off. Hyperframes is a separately installed CLI:
Kinocut sets telemetry opt-outs, skips passive update checks and disables
implicit capture/snapshot model analysis. Docker rendering and browser previews
without a verified opt-out require explicit telemetry consent.

These controls are not a network sandbox. Inspect executable scenes and project
assets before use. See the
[vision and network policy](https://github.com/KyaniteLabs/kinocut/blob/master/docs/VISION_PRIVACY.md)
for configuration, supported preview versions and limits.

[Documentation](https://github.com/KyaniteLabs/kinocut#readme) ·
[Release notes](https://github.com/KyaniteLabs/kinocut/releases) ·
[Issues](https://github.com/KyaniteLabs/kinocut/issues) ·
[Website](https://kinocut.dev/)
