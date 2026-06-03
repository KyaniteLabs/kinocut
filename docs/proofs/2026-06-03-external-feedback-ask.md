# External Feedback Ask - 2026-06-03

## Goal

Get one real outside signal for mcp-video without overselling it.

Ask for a run or a breakage report, not praise.

## Target Profile

- Technical founder building with agents
- Devrel / docs / demo builder
- Media automation builder
- Open-source maintainer who uses FFmpeg
- Creator tooling engineer
- MCP server/plugin builder

## Short Ask

```text
I am tightening up mcp-video, an open-source MCP server/Python tool that lets agents run guarded FFmpeg-style video workflows.

Could you try one receipt-backed proof run and tell me where it breaks or gets confusing?

Command:
uv run --no-project --with mcp-video python workflows/05-confidence-baseline/workflow.py

The useful feedback is:
1. Did install/run work?
2. Was the Video Receipt understandable?
3. What would make you trust this inside an agent workflow?
```

## Slightly Warmer Ask

```text
I am trying to make mcp-video boringly trustworthy for agentic media workflows.

The first proof path generates a tiny sample clip, transforms it, runs quality checks, creates a thumbnail/storyboard, and writes a Video Receipt so the agent's work is inspectable.

Would you be willing to run it once or scan the proof docs and tell me the first point where trust drops?
```

## Capture Format

| Person | Environment | Result | Friction | Follow-up |
| --- | --- | --- | --- | --- |
|  |  | install passed / failed / docs-only |  | issue / docs fix / testimonial / pilot invite |

## Do Not Claim

- Do not claim revenue.
- Do not claim users.
- Do not call it production-ready for every media workflow.
- Do not say the workflow is publishable without human review.

## Good Outcome

One honest breakage report is enough if it becomes a fix or proof note.
