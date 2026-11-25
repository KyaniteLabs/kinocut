# Install Kinocut Across Platforms

All configurations below launch the published **2.0.1** local stdio MCP server via [uv](https://docs.astral.sh/uv/) (`uvx`) with Kinocut's default **18-tool** surface (8 hot-path tools, 8 operation families, `list_operations`, and `describe_operation`).

**Prerequisites:** [FFmpeg](https://ffmpeg.org/) on `PATH` and `uv` (or `pip install kinocut==2.0.1`). Verify your machine with:

```bash
uvx --from kinocut==2.0.1 kino doctor
```

To expose a named profile or every tool by name, add `"KINOCUT_TOOLS": "profile:editor"` or `"KINOCUT_TOOLS": "all"` to your client's server environment block and restart the host. See [INSTALL.md](INSTALL.md) for optional extras.

---

## VS Code & GitHub Copilot

- **One-click install:** <a href="vscode:mcp/install?%7B%22name%22%3A%22kinocut%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22kinocut%3D%3D2.0.1%22%2C%22kino%22%2C%22--mcp%22%5D%7D">Install Kinocut in VS Code</a>
- **Workspace config:** copy [examples/vscode_mcp.json](../examples/vscode_mcp.json) to `.vscode/mcp.json`:

```json
{
  "servers": {
    "kinocut": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
    }
  }
}
```

## Cursor

- **One-click install:** <a href="cursor://anysphere.cursor-deeplink/mcp/install?name=kinocut&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJraW5vY3V0PT0yLjAuMSIsImtpbm8iLCItLW1jcCJdfQ%3D%3D">Install Kinocut in Cursor</a>
- **Manual config (`.cursor/mcp.json` or `~/.cursor/mcp.json`):**

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
    }
  }
}
```

Cursor marketplace bundle manifests also live in [plugins/kinocut/.cursor-plugin/plugin.json](../plugins/kinocut/.cursor-plugin/plugin.json).

## Codex CLI

Add Kinocut to `~/.codex/config.toml` (template: [examples/codex_config.toml](../examples/codex_config.toml)):

```toml
[mcp_servers.kinocut]
command = "uvx"
args = ["--from", "kinocut==2.0.1", "kino", "--mcp"]
```

Codex skill metadata lives in [skills/kinocut/agents/openai.yaml](../skills/kinocut/agents/openai.yaml) and [skills/kinocut-repurpose/agents/openai.yaml](../skills/kinocut-repurpose/agents/openai.yaml).

## Windsurf

Add Kinocut to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
    }
  }
}
```

## Zed

Add Kinocut under `context_servers` in your Zed `settings.json`:

```json
{
  "context_servers": {
    "kinocut": {
      "command": {
        "path": "uvx",
        "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"]
      }
    }
  }
}
```

## Cline & Roo Code

Add Kinocut to `cline_mcp_settings.json` (Cline) or `.roo/mcp.json` (Roo Code):

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut==2.0.1", "kino", "--mcp"],
      "disabled": false
    }
  }
}
```

## OpenCode

Copy [plugins/kinocut/opencode-plugin/opencode.json](../plugins/kinocut/opencode-plugin/opencode.json) into your project root or `~/.config/opencode/opencode.json`, or load `plugins/kinocut/opencode-plugin/index.js`. See [plugins/kinocut/opencode-plugin/README.md](../plugins/kinocut/opencode-plugin/README.md).

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kinocut": {
      "type": "local",
      "command": ["uvx", "kinocut==2.0.1"],
      "enabled": true
    }
  }
}
```

## Hermes Agent & Hermes Desktop

Install the unified Hermes plugin (MCP server, skills, and opt-in Desktop renders pane):

```bash
hermes plugins install kinocut
```

For manual `config.yaml` setup or tool allowlists, see [plugins/kinocut/README.md](../plugins/kinocut/README.md).

## Claude (Claude Code & Claude Desktop)

**Claude Code:**

```bash
claude mcp add kinocut -- uvx --from kinocut==2.0.1 kino --mcp
```

**Claude Desktop (`claude_desktop_config.json`):** copy [examples/claude_mcp_config.json](../examples/claude_mcp_config.json), or build the local `.mcpb` desktop extension as documented in [MCPB.md](MCPB.md).

## Gemini CLI

Add Kinocut to `~/.gemini/settings.json` (or install via the repository's [gemini-extension.json](../gemini-extension.json)):

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["kinocut==2.0.1"]
    }
  }
}
```
