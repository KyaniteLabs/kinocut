# mcp-video → Kinocut

## What changed

On **2026-07-10**, the project’s public identity became **Kinocut**.

| Surface | Before | After |
| --- | --- | --- |
| Product name | mcp-video | Kinocut |
| Python package | `mcp-video` | `kinocut` (canonical) |
| Import | `mcp_video` | `kinocut` (canonical) |
| CLI | `mcp-video` | `kino` / `kinocut` (+ compat `mcp-video`) |
| Site | GitHub Pages marketing | https://kinocut.dev/ |
| MCP Registry | former identity | `io.github.KyaniteLabs/kinocut` |
| Repo | mcp-video slug | `KyaniteLabs/kinocut` (GitHub redirect from old slug) |

## Compatibility (through at least 1.8.x)

- `pip install mcp-video` still works via a shim that installs Kinocut.
- `mcp_video` imports, `MCP_VIDEO_*` env vars, `~/.mcp-video` data, `mcp-video://` resources, and legacy receipt keys remain supported during the window.
- New integrations should use `kinocut`, `from kinocut import Client`, and `kino`.

## Why rename

The product is a **guardrailed local execution layer for agentic video**, not “MCP” as the brand. Kinocut names the job: cinema (`kino`) + cut, with trust/receipt semantics.

## For directories and roundups

Please list:

- **Name:** Kinocut (formerly mcp-video)  
- **Install:** `pip install kinocut`  
- **MCP:** `uvx --from kinocut kino` / registry `io.github.KyaniteLabs/kinocut`  
- **Site:** https://kinocut.dev/  
- **Repo:** https://github.com/KyaniteLabs/kinocut  

Version and tool counts: [`public_claims.json`](public_claims.json) (do not invent tip counts as a release).

## Related

- [DIRECTORY_REBRAND_STATUS.md](DIRECTORY_REBRAND_STATUS.md)
- [CHANGELOG.md](../CHANGELOG.md) `1.7.0`
