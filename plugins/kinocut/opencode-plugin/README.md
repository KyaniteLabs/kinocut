# Kinocut for OpenCode

This folder ships a ready-to-use OpenCode MCP configuration (`opencode.json`) and a minimal Node plugin descriptor/helper (`index.js`).

## Option 1: Copy `opencode.json` (recommended)

Copy `opencode.json` into your project root or merge its `mcp.kinocut` entry into `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kinocut": {
      "type": "local",
      "command": ["uvx", "kinocut==2.2.0"],
      "enabled": true
    }
  }
}
```

By default, Kinocut launches with its curated **18-tool default** surface (8 hot-path tools, 8 operation families, `list_operations`, and `describe_operation`). To register a named profile or the full catalog instead, add `"environment": { "KINOCUT_TOOLS": "profile:editor" }` (or `"all"`) under `mcp.kinocut` and restart OpenCode.

## Option 2: Load the plugin helper (`index.js`)

```js
const { kinocutOpenCodePlugin, createOpenCodeConfig } = require("./plugins/kinocut/opencode-plugin");

const descriptor = kinocutOpenCodePlugin();
const editorConfig = createOpenCodeConfig({ toolsProfile: "profile:editor" });
```

## Verify your environment

```bash
uvx kinocut==2.2.0 doctor
```

Requirements: [uv](https://docs.astral.sh/uv/) and FFmpeg on `PATH`.
Bundled skills (`kinocut`, `kinocut-repurpose`) live in `../skills/`.
