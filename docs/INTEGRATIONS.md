# Integrations

## Claude Code

```bash
pip install kinocut
claude mcp add kinocut -- uvx --from kinocut kino --mcp
kino doctor
```

Then use prompts from [PROMPTS.md](PROMPTS.md) or `$kinocut` skill.

## Cursor

Add MCP server config:

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino", "--mcp"]
    }
  }
}
```

Restart Cursor; confirm tools appear; run `search_tools` for `trim` / `receipt` / `workflow`.

## Generic MCP client (stdio)

Command: `uvx`

Args: `--from kinocut kino --mcp`

Transport: stdio

Registry id: `io.github.KyaniteLabs/kinocut`.

## Gemini CLI

Current supported Gemini CLI releases support MCP servers directly. Add this to
the appropriate settings file (project `.gemini/settings.json` or user
`~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino", "--mcp"],
      "trust": false
    }
  }
}
```

Alternatively, use the current Gemini CLI's project-scoped configuration command:

```bash
gemini mcp add --scope project kinocut uvx -- --from kinocut kino --mcp
gemini mcp list
```

Install FFmpeg, verify `kino doctor`, then use `/mcp` in Gemini CLI to inspect
connection status and discovered tools. Retain the client's workspace trust and
tool-confirmation controls. Start with a metadata-only inspection; a registered
optional tool does not establish that its model or provider is available.

Kinocut runs the media operation locally through stdio. The host agent may send
prompts and returned tool results to its model provider. Local execution alone
does not establish zero data egress: review the client's settings and the exact
tool result before passing private transcripts, frames, paths or media bytes.

The Google Gen AI Python SDK also documents **experimental** MCP session support.
That is a separate SDK integration, not a guarantee for every Gemini product or
the Live API. Native Gemini CLI MCP setup does not require an OpenAPI gateway.
A hosted gateway would need its own authentication, path confinement, resource
limits and data-boundary design.

Primary references: [Gemini CLI MCP documentation](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md)
and [Google Gen AI Python SDK](https://github.com/googleapis/python-genai#model-context-protocol-mcp-support-experimental).

## Host plugin packages

MCP transport and host plugin packaging are different contracts. Claude plugins,
Gemini CLI extensions and Agent Plugins have host-specific manifests and supported
components. Follow the selected client's current documentation; one `plugin.json`
does not establish compatibility with every agent client. Kinocut's existing MCP
configuration is sufficient for the direct stdio integrations above.

## Python automation / CI

```bash
pip install kinocut
python -c "from kinocut import Client; print(Client().info('clip.mp4'))"
```

CI tips:

- Install FFmpeg in the job image  
- Run `kino doctor --json` and assert `required_ok`  
- Optional: `python scripts/golden_path.py` on a runner with FFmpeg  

## Hyperframes

Optional code-to-video path. Needs Node 22+ and Hyperframes CLI.  
Post-process renders with Kinocut FFmpeg tools. See tool reference Hyperframes section in [TOOLS.md](TOOLS.md).

## FFmpeg

Required system dependency — not bundled. Kinocut wraps FFmpeg with validation and guardrails; it does not replace installing FFmpeg.

## MCPB / Desktop

Staged package in `mcpb/`. Not a fully self-contained native bundle yet. [MCPB.md](MCPB.md).

## Compatibility

Former `mcp-video` CLI/import/env still work during the compatibility window. [RENAME.md](RENAME.md).
