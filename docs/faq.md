# Frequently Asked Questions

## What is Kinocut?

Kinocut is an open-source MCP server, Python client and `kino` CLI that lets AI agents
edit video through typed FFmpeg tools. Each edit is checked before FFmpeg runs, writes a
new file unless you allow an overwrite, and returns a structured result. Quality gates
catch black frames, silence and bad loudness, and a Video Receipt records what ran.
Kinocut was called `mcp-video` until 2026-07-10.

## What is MCP?

The Model Context Protocol is a standard way for AI agents such as Claude Code and Cursor
to call external tools. Kinocut runs as a local stdio MCP server, the transport every MCP
client supports.

## Is Kinocut on the MCP Registry?

Yes, as `tech.kyanitelabs/kinocut`. The
[official MCP Registry entry](https://registry.modelcontextprotocol.io/v0/servers/tech.kyanitelabs%2Fkinocut/versions/latest),
PyPI and the GitHub release report **2.0.0** (published 2026-11-10). The compatibility
package `mcp-video==1.6.21` pins `kinocut==2.0.0`. The legacy id
`io.github.KyaniteLabs/kinocut` is deprecated. Check the registry and PyPI for the live
version; [public_claims.json](public_claims.json) records what this repository last
verified.

## Where is the source?

GitHub ([KyaniteLabs/kinocut](https://github.com/KyaniteLabs/kinocut)) is canonical:
issues, pull requests and releases happen there. A Forgejo copy is a downstream mirror.

## Which AI agents work with Kinocut?

Any MCP client that can launch a stdio server: Claude Code, Claude Desktop, Cursor,
Codex, Gemini CLI, Windsurf, Cline and others. Setup for each is in
[INTEGRATIONS.md](INTEGRATIONS.md).

## How many tools will my agent see?

By default, 18:

- an 8-tool hot path: `video_info`, `video_trim`, `video_merge`, `video_add_text`,
  `video_add_audio`, `video_extract_frame`, `video_shorts`, `video_doctor`;
- eight operation families (`video_edit_ops`, `video_effects_ops`, `audio_ops`,
  `video_ai_ops`, `image_ops`, `video_qc_ops`, `video_plan_ops`, `platform_ops`) that
  reach every other operation;
- `list_operations` and `describe_operation` to find an operation and fetch its schema.

`KINOCUT_TOOLS=profile:<name>` lists one job's tools by name (for example
`profile:editor`), and `KINOCUT_TOOLS=all` lists every tool: 206 in 2.0.0. See [MCP_TOOL_FAMILIES.md](MCP_TOOL_FAMILIES.md).

## How does my agent find an operation that is not on the hot path?

Call `list_operations` for a family to see its operations, `describe_operation` for one
operation's parameters, then call the family tool with
`{"operation": "...", "params": {...}}`. Family dispatch runs the same code as the
named tool.

## Do I need FFmpeg installed?

Yes. FFmpeg and ffprobe must be on your `PATH`; Kinocut does not bundle them. macOS:
`brew install ffmpeg`. Ubuntu: `sudo apt install ffmpeg`. Run `kino doctor` to check.

## Does it work on Windows?

The Python package, CLI and MCP server are cross-platform, and the desktop-extension
package is validated on Windows, macOS and Linux. The full test suite runs on Linux, so
check optional engines on your own Windows host with `kino doctor`. See
[PLATFORM_PARITY.md](PLATFORM_PARITY.md).

## What video formats are supported?

It depends on the operation and your FFmpeg build. Common workflows use MP4, WebM, MOV,
MKV, AVI and GIF. A decoder accepting a file does not mean every operation admits it;
tools reject unsupported containers and codecs with a structured error.

## Can I use it without an AI agent?

Yes. The Python client (`from kinocut import Client`) and the `kino` CLI use the same
engine as the MCP server.

## How do I install it?

```bash
pip install kinocut==2.0.0
kino doctor
```

Optional extras add transcription, stem separation, upscaling, object matte and more.
None are needed for core editing. The full list is in [INSTALL.md](INSTALL.md#optional-extras).

## How do I connect Kinocut to Claude Code?

Install FFmpeg and [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
claude mcp add kinocut -- uvx --from kinocut==2.0.0 kino --mcp
```

## Why not call FFmpeg directly?

An agent building FFmpeg commands from user input can corrupt files, overwrite sources
or hang on a bad filter. Kinocut validates paths and parameters, runs preflight checks
(filter bounds, merge compatibility, audio levels, overlay timing, text layout), bounds
each subprocess, and returns errors that name the exact retry call. Workflows record
Video Receipts with source and output hashes.

## Does local-first mean no data leaves my machine?

Core FFmpeg edits run locally. Your AI host decides which prompts, results or media it
sends to its model, and optional services you configure have their own policies.
Kinocut's own vision calls are off by default (`KINOCUT_VISION_MODE=off`). Installing
packages, fetching URL inputs and first-use model weights also use the network. See
[VISION_PRIVACY.md](VISION_PRIVACY.md).

## Is mcp-video a separate product?

No. Kinocut is the renamed project. `pip install --upgrade 'mcp-video==1.6.21'` installs
Kinocut 2.0.0, and the `mcp-video` command and `mcp_video` import still work. New
integrations should use `kinocut`, `kino` and `from kinocut import Client`.

## Does Kinocut generate video?

No. No generation adapter exists. Kinocut edits, checks and renders real media.
Planning helpers such as `shot_prompt_render` write generic prompts
(`prompt_dialect="generic"`) and never call a generation provider.

## What are the AI-powered features?

Optional model-backed operations: Whisper transcription, Demucs stem separation and
Real-ESRGAN upscaling. The AI family also holds deterministic helpers such as silence
and scene detection and color grading. Model output is evidence for review, not
acceptance.

## Can it edit Insta360 X4 360 video?

Yes, from a **stitched 360 MP4**, not a raw `.insv`. `video_intent` with a 360 goal (or
`Client.propose_360_assembly`) writes a reviewable `360_assembly_plan`. Approve it, then
render split, switch, picture-in-picture or single view. Available in published
`kinocut==2.0.0`. See [360_ASSEMBLY.md](360_ASSEMBLY.md).

## What do the Hyperframes and Revideo tools add?

Code-driven motion graphics. Hyperframes tools scaffold, render, snapshot and inspect
HTML compositions and need the separately installed Hyperframes CLI. Four Revideo tools
install and render TypeScript scenes locally with Node.js. Neither is needed for FFmpeg
editing.

## Can I cut a product out of a turntable or tabletop video?

Yes, on the same `hyperframes-remove-background` command. The default model is
**people** (`u2net_human_seg`). For products and other objects, pass
`--model birefnet-general` after `pip install "kinocut[object-matte]==2.0.0"`. That
optional object-matte extra is available in published 2.0.0 (first shipped in 1.15.1).
`--info` lists models without downloading. No new MCP tool. See
[PRODUCT_MATTE.md](PRODUCT_MATTE.md).

## How can a person review a cut?

`video_review_card` turns a finished cut into a review card with a contact sheet, facts
and Approve & export, Dig in and Try another range buttons for Hermes Desktop chat.
`kino release-checkpoint` runs the release gates. A Video Receipt records provenance and
review status; it is not a human sign-off, and Kinocut never posts anything.

## Is it free?

Kinocut is open source under Apache-2.0 with no license fee. Your hardware, AI host and
any optional services or separately licensed models may cost money.

## How fast is it?

It depends on the source, codec, operations, hardware and optional models. Some
operations copy streams; others decode and re-encode. Measure on your own media.

## Can I use it in production?

Kinocut returns structured errors, validates inputs, bounds FFmpeg runs and ships with
release gates you can run in CI. Keep a person in the loop: automated checks catch
technical faults, not whether the cut is good. See
[QUALITY_EVIDENCE.md](QUALITY_EVIDENCE.md) for what is and is not measured.

## Who is Kinocut for?

1. **Agent users:** Claude Code and Cursor operators who want structured video tools.
2. **Media operators:** podcast and social teams automating cuts with human approval.
3. **Stack evaluators:** engineers comparing local MCP video options.

See [RECOMMEND.md](RECOMMEND.md) and [COMPARE.md](COMPARE.md).

## Is there a paid enterprise tier?

No. See [ENTERPRISE.md](ENTERPRISE.md) for commercial notes.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md): fork, branch, add tests and open a pull
request on GitHub. All pull requests need passing CI.
