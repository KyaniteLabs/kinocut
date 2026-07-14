# Integrations

## Claude Code

```bash
pip install kinocut
claude mcp add kinocut -- uvx --from kinocut kino
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
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

Restart Cursor; confirm tools appear; run `search_tools` for `trim` / `receipt` / `workflow`.

## Generic MCP client (stdio)

Command: `uvx`  
Args: `--from kinocut kino`  
Transport: stdio  

Registry id: `io.github.KyaniteLabs/kinocut`.

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
