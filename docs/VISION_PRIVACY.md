# Vision and network controls

Kinocut 1.16.5 disables its optional model calls by default. An inherited API key,
`use_ai=true`, a model name, or `require_vlm=true` does not grant permission to
send frames. Local FFmpeg color grading does not call a model.

## Use the host's chosen model

For provider-neutral review, use `video_thumbnail` or `video_qc_vision` to prepare
local images, then inspect those images with the agent host's image input tools.
For product analysis, call `image_analyze_product(use_ai=false)` for local colors
and let the host describe the image. Hermes then owns model selection, credentials,
local or hosted execution, and any fallback policy. Check the host's configuration
when local-only processing is required. Kinocut's standalone MCP process does not
automatically inherit Hermes's model routing.

Treat host observations as separate evidence: they do not turn Kinocut's
`assessment_status=not_evaluated` into a scored QC pass. Human review remains
necessary. Missing image support must produce an explicit limitation.

## Optional legacy adapters

`KINOCUT_VISION_MODE` is an operator environment setting, not a tool parameter:

| Mode | Product description (`use_ai=true`) | Semantic QC |
| --- | --- | --- |
| `off` (default) | Refused before provider execution | Frames retained; model assessment unavailable |
| `local` | Requires loopback `KINOCUT_VISION_BASE_URL` | Unavailable; fixed cloud worker cannot serve this route |
| `remote` | Explicit permission for configured or default endpoint | Requires model and Anthropic key, with no custom base URL |

The product adapter speaks the Anthropic-compatible Messages protocol, including
for local servers. This is not generic OpenAI-compatible support. Configure
`KINOCUT_VISION_MODEL` for your local server; no local API key is required.
Local requests ignore environment proxies, reject redirects, and never retry
through a cloud endpoint. Custom remote endpoints require their own
`KINOCUT_VISION_API_KEY`; the default endpoint requires `ANTHROPIC_API_KEY`.
The product adapter disables ambient auth-token discovery and rejects nonempty
`ANTHROPIC_CUSTOM_HEADERS` to prevent inherited credentials reaching another
endpoint. The default remote product endpoint is
`https://api.anthropic.com`, with the legacy default model
`claude-sonnet-4-20250514` unless overridden. The adapters are optional; their
availability does not establish model accuracy or current vendor access.

With explicit remote consent, the product adapter sends image bytes and a text
prompt to the selected endpoint. The separate QC worker sends sampled keyframe
bytes and a prompt only to `https://api.anthropic.com/v1/messages`, and requires
`KINOCUT_VISION_MODEL` plus `ANTHROPIC_API_KEY`. Setting any
`KINOCUT_VISION_BASE_URL` disables that worker so a local/custom product route
cannot silently activate cloud QC. Neither adapter falls back to another provider.

Set `KINOCUT_VISION_MODE=off` to disable both adapters. This does not control the
host's own model calls or sandbox all network access.

## Hyperframes

Hyperframes is an external CLI selected from the operator's configured command,
project-local Node installation, or `PATH`; Kinocut does not automatically install
it. Pin and review that CLI separately. Kinocut defaults telemetry off and suppresses
automatic skill installation and passive update checks in both commands and
preview processes. With telemetry off, browser previews require exactly
Hyperframes **0.8.104 or 0.8.140**, whose browser opt-out was verified; other
versions are refused before replacing an existing preview. Docker rendering is
also refused because upstream does not forward the telemetry opt-out into its
container. Explicit `KINOCUT_HYPERFRAMES_TELEMETRY=true` permits these optional
paths and stops forcing telemetry off; existing upstream opt-outs are preserved.
This consent never enables model uploads. Invalid consent values fail closed.
The wrapper always passes `--skip-vision` for website capture,
and `--describe false` for snapshots/stills. Ambient model-provider credentials
are removed from both child environments as defense in depth. These flags
prevent upstream captions/analysis triggered by inherited OpenRouter,
Google/Gemini or Vertex credentials. Use the host's configured image model for
those observations.

Capture still downloads the requested website and assets. Catalog/template,
browser and local model features may download supporting resources. Rendering
executes HTML/JavaScript whose referenced assets may make network requests;
inspect projects before running them. This wrapper is not a network sandbox and
cannot enforce the behavior of an arbitrary replacement CLI. These controls were
checked against upstream 0.8.30/0.8.104/0.8.140; CI pins are validation fixtures, not a
runtime dependency lock for an operator-installed executable.

## Revideo and other network access

The four explicit `revideo_*` tools stage, install and render TypeScript animation
projects with Node, a headless browser and FFmpeg. They are separate from ordinary
FFmpeg edits. Dependency installation uses `npm ci` and accesses the npm registry.
Kinocut sets `DISABLE_TELEMETRY=true` on every npm child by default, including when
that variable was inherited as false. Only `KINOCUT_REVIDEO_TELEMETRY=true` opts
into the pinned Revideo renderer's telemetry. Its inspected render-start event
contains an anonymous identifier, package version and event name, not media.

The first package launch downloads dependencies from PyPI. URL inputs download
requested media; font and model-weight features download assets from GitHub.
Vision mode does not disable these downloads. Review each optional feature's
network use before invoking it.
