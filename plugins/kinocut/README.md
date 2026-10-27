# Kinocut plugin

![Kinocut icon](icon.png)

Guarded local video editing for AI agents. The plugin adds the Kinocut MCP
server and two skills (`kinocut`, `kinocut-repurpose`) to your agent.

Plugin bundle **1.16.7** pins the separately versioned Kinocut runtime
**1.16.5**. The legacy `mcp-video` compatibility package **1.6.20** installs
that same runtime. Catalog entries use the bundle version; launchers use the
runtime version.

Local FFmpeg editing and color grading need no account or API key. Network use
depends on the features you choose:

- The first launch downloads Kinocut and its dependencies from PyPI.
- URL inputs download the requested media.
- Font and model-weight features download assets from GitHub when needed.
- Optional Kinocut model calls default off. When explicitly enabled, legacy product
  descriptions send the selected image to an Anthropic-compatible endpoint; the
  separate sampled-frame quality-check worker uses Anthropic.
- Revideo dependency installation runs `npm ci` and may download renderer dependencies.
  Revideo telemetry defaults off; only an explicit operator
  `KINOCUT_REVIDEO_TELEMETRY=true` enables it.
- Hyperframes is a separate CLI. Kinocut disables its telemetry and passive update
  checks by default, removes known provider credentials from its child environment,
  and disables implicit capture/snapshot model analysis. With telemetry off, browser
  previews require verified CLI 0.8.104 or 0.8.140. Docker rendering and other preview
  versions require explicit operator `KINOCUT_HYPERFRAMES_TELEMETRY=true` consent.

These controls are not a network sandbox. Project code, assets, requested URLs and
dependency installation can still access the network. Review optional features
before using them.

## Vision review and provider choice

Keep `KINOCUT_VISION_MODE=off` unless you choose to enable a legacy adapter.
An inherited API key or `use_ai=true` cannot override that setting. To use Hermes's
chosen provider, prepare local frames with `video_thumbnail` or `video_qc_vision`
and inspect them through Hermes's image tools. For local product colors, use
`image_analyze_product(use_ai=false)`. Hermes owns its model selection, credentials
and fallback policy; Kinocut's MCP process does not automatically inherit them.

The optional product adapter supports explicit `local` and `remote` modes using
the Anthropic-compatible Messages protocol. Local mode requires a loopback endpoint,
has no cloud fallback and cannot activate the separate Anthropic QC worker.
Missing model support must be reported as unavailable; host observations do not
turn an unevaluated Kinocut assessment into a scored pass. See the
[vision and network policy](https://github.com/KyaniteLabs/kinocut/blob/v1.16.5/docs/VISION_PRIVACY.md) for configuration and limits.

Prefer new output paths. Never target credentials, session files or agent
configuration directories.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- FFmpeg and ffprobe on `PATH`
- Python 3.11 or newer (uv installs it if needed)

Check your setup with `uvx kinocut==1.16.5 doctor`.

## Claude installation

Claude Code and Cowork run the pinned `uvx kinocut==1.16.5` launcher.
The Python project and `uv.lock` in the repository's `packaging/claude-plugin/`
directory record exact core dependency versions, public PyPI sources and artifact
hashes for directory review. They live outside this folder, so hosts that read a
plugin's `pyproject.toml` as its dependencies install nothing extra. The directory's
locked-launcher check requires this plain pinned command, without environment
overrides or dependency-file options.

uvx pins Kinocut itself and resolves its dependencies when creating a tool
environment; it does not consume that uv.lock. That lock is an audit
snapshot. uv caches the environment outside the installed plugin files.

The first launch downloads the dependencies from PyPI. Later launches
reuse that environment. This does not bundle FFmpeg or optional AI packages.
Cursor, MiniMax, Kimi and Agent Plugins hosts retain the pinned
`uvx kinocut==1.16.5` launcher below.

Claude's directory still requires manual review for registry package launchers,
including locked ones. The lock documents a dependency snapshot; it does not guarantee
approval or a Verified badge. The directory-only icon, documentation, support,
privacy and terms fields are intentional listing metadata.

## What's in this folder

| Agent | Files |
| --- | --- |
| Claude Code / Cowork | `.claude-plugin/plugin.json`, `.mcp.json`, `skills/` |
| Hermes Agent and other Agent Plugins v1 hosts | `plugin.json`, `mcp.json`, `skills/` |
| OpenClaw / ClawHub | Claude Code layout above, bundled icon |
| Grok Build | Claude Code layout above |
| ZCode | Installs from the Claude Code marketplace |
| MiniMax | `.minimax-plugin/plugin.json`, `kinocut.mcp.json`, bundled icon |
| Cursor | Repository marketplace manifest, `.cursor-plugin/plugin.json`, `mcp.json`, `skills/` |
| Kimi Code | `kimi.plugin.json`, `skills/` |
| OpenCode | Configuration in `opencode-plugin/README.md` |

## Manual setup for any MCP client

Clients can also use the pinned configuration directly:

```json
{
  "mcpServers": {
    "kinocut": { "command": "uvx", "args": ["kinocut==1.16.5"] }
  }
}
```

## Narrowing the tool list

Kinocut exposes about 200 MCP tools. A host tool allowlist reduces the schemas
sent with each model request. For Hermes, this small inspection-and-trim set
goes in `mcp_servers` in your Hermes `config.yaml`:

```yaml
mcp_servers:
  kinocut:
    command: uvx
    args: ["kinocut==1.16.5"]
    tools:
      include: [search_tools, video_info, video_trim, video_thumbnail]
      resources: false
      prompts: false
```

Hermes uses this explicit, same-name server configuration in preference to the
plugin's launcher. Keep its version aligned with the plugin's `mcp.json` when
updating. Run `/reload-mcp` after changing the configuration. Use server-native
tool names in `include`, and add the edit and quality-check tools your workflow
needs. `search_tools` helps discover names; it does not enable excluded tools or
hide schemas by itself. See the [Hermes MCP configuration reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference/).

For other hosts, use their tool-filtering controls if available.

## Links

- Website: https://kinocut.dev/
- Source and issues: https://github.com/KyaniteLabs/kinocut
- License: Apache-2.0
