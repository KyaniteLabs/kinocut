# Kinocut for OpenCode

Add the Kinocut MCP server to `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kinocut": {
      "type": "local",
      "command": ["uvx", "kinocut==1.16.2"],
      "enabled": true
    }
  }
}
```

Requirements: [uv](https://docs.astral.sh/uv/) and FFmpeg on `PATH`.
Skills live in `../skills/`.
