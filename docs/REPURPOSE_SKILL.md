# Kinocut Repurpose Skill

The path-based repurpose skill lives at
[`../skills/kinocut-repurpose/SKILL.md`](../skills/kinocut-repurpose/SKILL.md). It is a
pre-kernel guide for Claude Code-compatible hosts that can discover local skills from a
project path.

Install from the repository root:

```bash
mkdir -p .claude/skills && cp -R skills/kinocut-repurpose .claude/skills/kinocut-repurpose
```

Then configure Kinocut as the MCP server if the host supports MCP:

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

The skill intentionally uses only current shipped tools: `video_repurpose_plan`,
`video_repurpose`, `repurpose-plan`, `repurpose`, and existing inspection/review helpers.
It does not publish, schedule, upload, or invent any post-render command.

Run the deterministic demo:

```bash
python examples/repurpose_current_tools_demo.py --output-dir /tmp/kinocut-repurpose-demo
```

For a no-render preview:

```bash
python examples/repurpose_current_tools_demo.py --dry-run
```
