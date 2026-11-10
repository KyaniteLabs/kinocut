<!-- mcp-name: tech.kyanitelabs/kinocut -->

# Kinocut

Guarded local video editing for agents, with a CLI, Python client and MCP server.
Kinocut uses FFmpeg and ffprobe for media inspection, editing, subtitles, audio
and quality checks. Optional workflows include Hyperframes, Revideo and model-assisted
analysis.

## Install and inspect

Requires Python 3.11 or newer, plus FFmpeg and ffprobe on `PATH`.

```bash
pip install kinocut==1.16.5
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
