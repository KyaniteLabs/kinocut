# Gemini / Claude integration claim review

Read-only verification, 2026-09-30 UTC. User source: `/workspace/attachments/e4037e9e-e683-4196-82b0-779653b86f66/Pasted text.txt`. No Kinocut edits, credentials, provider calls, cloud runtime, remote publication, package installation, or TLS bypass. Official sources cloned using native Git HTTPS; public GitHub HTML search used only for discovery.

## Findings

1. **The claim that Gemini requires Vertex Extensions/function calling instead of native MCP integration is materially incomplete.** Gemini MODEL/API is not itself a local-process host, but **Gemini CLI is a native MCP client/agent host**, with stdio, SSE, and Streamable HTTP discovery/execution, user confirmation, resources, and configurable tool allowlists. It supports `.gemini/settings.json` and `gemini mcp add`. Kinocut already exposes stdio MCP, so no OpenAPI/reverse-proxy gateway is needed for this normal local integration.
2. **Official Google Python SDK has built-in MCP support, labelled experimental.** README demonstrates `mcp.ClientSession`/stdio connection and `client.aio.models.generate_content(config=GenerateContentConfig(tools=[session]))`, including automatic function calling. This supports a plausible Kinocut adapter through existing MCP, but does NOT demonstrate that every Kinocut schema is accepted or every model supports every media/tool feature. No paid end-to-end Gemini run was performed. Avoid recommending automatic execution of the complete tool catalog without validation/approval boundaries.
3. **Live API client-side tools are real, but “local execution” does not make inference local or media egress automatic/safe.** Official `live.py` shows `config.tools`, server `tool_call`, and client `send_tool_response(function_responses=...)`; explicit audio/video frames are sent over the remote WebSocket by `send_realtime_input(audio/video/media=...)`. Responses (including filenames, transcripts, descriptions, or attached media if provided) go to Google. Returning a local output path does not upload its video bytes or make that path readable by the cloud model. Sending media is a separate explicit application choice. Minimal documentation should state prompts/tool schemas/results are cloud inputs; any snapshots/audio/video need explicit user-authorized egress. Do not add a cloud visual reviewer in this task.
4. **Agent Plugins is a real published portable specification, not an invented standard.** Exact primary repository publishes 1.0.0; 1.1.0 is a working draft. Governance roster names individual maintainers with Amazon, Cursor, Microsoft, OpenAI, Vercel affiliations. Official site repeats this roster; it does not list Google in that statement. Thus the specific pasted Google/OpenAI/Microsoft/Cursor endorsement/date story is only partially supported; no evidence here establishes Google backing or an August announcement by every named vendor. Do not say the standard does not exist, and do not turn absence from this roster into proof Google never supported it.
5. **The “universally pluggable into any 2026 client” promise is contradicted by the spec's scope.** Supported clients can adopt only skills; unsupported MCP transports are skipped. Canonical portable `plugin.json` is CLOSED and cannot inline `mcpServers`; portable MCP lives in root `mcp.json` with matching `$schema` and explicit `type`. Agent Plugins does not standardize hooks/agents/commands/LSP as portable v1 components. Official compatible-client list documents individual support (VS Code, Cursor, GitHub Copilot, ChatGPT/Codex, Kiro, etc.); Gemini CLI/Claude Code are not listed there at the pinned site revision. That list is not proof those clients can never adopt the spec.
6. **Claude Code native plugin structure is independently established.** Official Anthropic repository shows `.claude-plugin/plugin.json`, optional root `.mcp.json`, skills/commands/agents/hooks. MCP config can be inline in the native Claude plugin manifest or separate `.mcp.json`; this differs from the portable Agent Plugins closed root manifest. Google native extension manifest is `gemini-extension.json`, also distinct. A single filename is not an integration guarantee. Reuse one canonical Kinocut skill/server contract and generate/validate small host-specific packaging adapters if packaging is desired.
7. **`--mcp` is a useful explicit launch flag but is NOT strictly required by current Kinocut.** Current source SHA `0ff4fa51518b11aa2e36f74e0c5cc7287c5d5510`, `kinocut/__main__.py:214`, runs MCP when `args.mcp OR args.command is None`. Existing `claude mcp add kinocut -- uvx --from kinocut kino` therefore launches MCP today. Explicit `kino --mcp` makes intended mode clearer and future-proof; do not describe this existing recipe as broken.

## Pinned official evidence

### Google Gemini CLI
SHA `38700b4b38bf387dafded6c97c3f190d084b49e9`, 2026-09-29T21:40:04Z.
- Native MCP discovery/execution/transports/config/allowlists and add syntax: https://github.com/google-gemini/gemini-cli/blob/38700b4b38bf387dafded6c97c3f190d084b49e9/docs/tools/mcp-server.md
- Actual `mcp add` parser supports `--` separator for server args: https://github.com/google-gemini/gemini-cli/blob/38700b4b38bf387dafded6c97c3f190d084b49e9/packages/cli/src/commands/mcp/add.ts
- Native `gemini-extension.json`, reusable agent skills plus MCP: https://github.com/google-gemini/gemini-cli/blob/38700b4b38bf387dafded6c97c3f190d084b49e9/docs/extensions/writing-extensions.md

### Google GenAI Python SDK
SHA `94b371d7ee7b2241be32a1efb78e5fa8cfb791de`, 2026-09-29T20:03:46-07:00.
- Experimental built-in MCP stdio `tools=[session]` README: https://github.com/googleapis/python-genai/blob/94b371d7ee7b2241be32a1efb78e5fa8cfb791de/README.md#model-context-protocol-mcp-support-experimental
- SDK actual MCP call and tool result forwarding: https://github.com/googleapis/python-genai/blob/94b371d7ee7b2241be32a1efb78e5fa8cfb791de/google/genai/_extra_utils.py#L416
- Live input and tool responses transmit to remote WebSocket: https://github.com/googleapis/python-genai/blob/94b371d7ee7b2241be32a1efb78e5fa8cfb791de/google/genai/live.py#L258 and #L363

### Anthropic Claude Code
SHA `732e167ee9d71296b4b63d6f529ac1334513826a`, 2026-09-29T23:30:04-07:00.
- Official native plugin layout: https://github.com/anthropics/claude-code/blob/732e167ee9d71296b4b63d6f529ac1334513826a/plugins/README.md#plugin-structure
- Native plugin MCP config alternatives: https://github.com/anthropics/claude-code/blob/732e167ee9d71296b4b63d6f529ac1334513826a/plugins/plugin-dev/skills/mcp-integration/SKILL.md
These skill files were read as primary product documentation evidence, not invoked as task workflows or authorization.

### Portable Agent Plugins
Spec SHA `ff8ab5e392cc87bd88d87c060815a87490e51003`, 2026-08-19T11:34:23-05:00.
- Publication status: https://github.com/agentplugins/agent-plugins-spec/blob/ff8ab5e392cc87bd88d87c060815a87490e51003/README.md
- Actual individual/affiliation roster: https://github.com/agentplugins/agent-plugins-spec/blob/ff8ab5e392cc87bd88d87c060815a87490e51003/MAINTAINERS.md
- Normative v1 fixed locations/closed manifest/transport/incremental adoption: https://github.com/agentplugins/agent-plugins-spec/blob/ff8ab5e392cc87bd88d87c060815a87490e51003/spec/1.0.0.md
- Schema: https://github.com/agentplugins/agent-plugins-spec/blob/ff8ab5e392cc87bd88d87c060815a87490e51003/schemas/1.0.0/plugin.schema.json
Official site SHA `f399975c2ac012961df4a8edfd9036bb017da95f`, 2026-09-22T07:54:53-07:00:
- Roster: https://github.com/agentplugins/agent-plugins-site/blob/f399975c2ac012961df4a8edfd9036bb017da95f/content/docs/index.mdx
- Documented individual supported clients/transports: https://github.com/agentplugins/agent-plugins-site/blob/f399975c2ac012961df4a8edfd9036bb017da95f/lib/compatible-clients.ts
Reference example SHA `5f3f5084a821aefa792e79500dd8f0462ab83473`, 2026-08-05T07:45:20-05:00:
- Additive migration and separate platform compatibility packaging: https://github.com/agentplugins/agent-plugins-example/blob/5f3f5084a821aefa792e79500dd8f0462ab83473/README.md

## Minimal concrete documentation recommendation

Add Gemini CLI section to `docs/INTEGRATIONS.md`, preserving the current stdio server and canonical skill. Prefer explicit launch mode in all current setup snippets when editing them. No new provider/gateway runtime needed.

Gemini project-local setup (command parser verified in pinned official source; not executed here):

```bash
gemini mcp add --scope project kinocut uvx -- --from kinocut kino --mcp
gemini mcp list
```

Or `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino", "--mcp"],
      "cwd": "/absolute/path/to/media-workspace",
      "trust": false
    }
  }
}
```

`cwd` is optional; if supplied it must point at the operator's actual workspace, not a literal placeholder. `trust:false` preserves host confirmation. `uvx`/Kinocut/system FFmpeg must be available. Do not assert paid-host end-to-end tested or API-supported-media inspection solely from schema discovery. Optionally document `includeTools` as a host-level allowlist to reduce exposed catalog size; `search_tools` alone cannot reduce eagerly loaded definitions or enable an excluded tool.

Claude explicit-mode recipe:

```bash
claude mcp add --scope project --transport stdio kinocut -- uvx --from kinocut kino --mcp
```

Short boundary paragraph: “Kinocut executes media operations locally through MCP. Gemini/Claude inference can still receive prompts, tool definitions, arguments and returned metadata. Uploading images, audio or video is a separate application action requiring your authorization. Local file paths do not transfer media.”

For optional future portable packaging, valid minimal root `plugin.json` has `$schema=https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`, `name=kinocut`; root `mcp.json` uses matching MCP schema, `mcpServers.kinocut.type=stdio`, `command=uvx`, `args=[--from,kinocut,kino,--mcp]`. Preserve native Gemini/Claude adapters and validate actual target clients; never promise universal compatibility. Default portable stdio cwd is plugin root per spec, so workspace-relative media paths need explicit absolute inputs or a host adapter, not an invented arbitrary cwd accepted by the standard.
