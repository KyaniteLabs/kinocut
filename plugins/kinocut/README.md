# Kinocut — Wave 3 vendor-surface package (STAGED, unsubmitted)

STAGED PACKAGING ONLY. Not submitted, not listed, not published.
Wave 3 vendor-surface packaging for in-repo review. CEO-gated per surface.
Voice assets are DO-NOT-COMMIT. Copy pack remains ungated draft.


Version: `1.16.1`

## Surfaces in this tree

- Claude Code: `.claude-plugin/plugin.json` + `.mcp.json`
- ZCode: `.zcode-plugin/plugin.json` (flat skills)
- MiniMax community format: `.minimax-plugin/plugin.json` + `kinocut.mcp.json` + `icon.png`
- Grok catalog payload: `.grok-plugin/entry.json` (UNSUBMITTED, SHA unpinned)
- OpenCode npm source: `opencode-plugin/` (`private: true`)
- Kimi: `kimi-plugin/README.md`
- DSH: blocked, see `dsh/README.md`

## MCP launch (stdio, if applicable)

```
uvx kinocut
```

## Explicit non-actions

- No marketplace upload, directory submit, npm publish, or MCP registry publish.
- No GPU window. No CS candidate verdict.
- Publishing/listing remains CEO-gated per surface.

## Gaps still blocked

- Claude / ZCode / Grok / Kimi / OpenCode / MiniMax / DSH listing = CEO-gated; nothing submitted.
- Grok SHA pin requires the merged commit; placeholder PIN-AFTER-MERGE.
- DSH bundle schema unverified.
- Hosted remote `https://mcp.kyanitelabs.tech/mcp` is recorded on repo `server.json` remotes; tools/call remains CEO-held bearer-closed.
- Voice/copy gate still BLOCKED (ungated copy pack not used here).
- Icon eye-gate still pending (plugin reuses mcpb/icon.png; not a Wave 3 icon-family accept).
