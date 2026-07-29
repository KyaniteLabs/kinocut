# Kinocut

Local-first FFmpeg tools, Video Receipts, quality gates, Hyperframes, and Shorts/Reels repurposing — for Claude Code, Cursor, and any MCP client. Free, Apache-2.0. Formerly mcp-video.

**Who it is for:** people who need agent-repeatable local video edits with a receipt a human can approve — not a hosted editor.

**What you get:** CLI + MCP tools that turn a local interview or podcast into captioned vertical clips with a Video Receipt you can re-run.

## Why it wins

- **Repurposing with receipts** — one recording → captioned Shorts/Reels/TikTok packages with manifests and review artifacts
- **Podcast and interview cuts** — strongest segment, audio normalize, chapters, export
- **Agent-driven media in CI** — repeatable edits from Claude Code, Cursor, Codex-style clients, or scripts

## Try it

```bash
pip install -U kinocut
kinocut --help
```

Published package: **[1.11.1](https://github.com/KyaniteLabs/kinocut/releases/tag/v1.11.1)** (2026-07-24). Install matrix and golden path live in `docs/`.

## Proof

| Surface | Tip |
| --- | --- |
| PyPI / npm / GitHub Release | **1.11.1** — `pip install -U kinocut` |
| This repository (`master`) | MCP + CLI surface beyond the last release; see release notes before treating tip as published |

## Docs

- [Install matrix](docs/INSTALL.md)
- [Golden path](docs/GOLDEN_PATH.md)
- [Prompts](docs/PROMPTS.md)
- [Tutorial: podcast to Shorts](docs/TUTORIAL_PODCAST_TO_SHORTS.md)
- [Compare](docs/COMPARE.md)
- [When to recommend](docs/RECOMMEND.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
