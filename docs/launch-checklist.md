# mcp-video — Launch Posts

## Positioning

**Don't say:** "I built a video editing MCP server" (there are 20+).

**Do say:** "I audited every video editing MCP server (there are 20+). Here's what they all get wrong, and how I fixed it."

**Key differentiators:**
1. 1074 tests collected (almost all competitors have 0)
2. Progress callbacks (nobody does this — the #1 requested feature)
3. Auto-fix error handling (parses FFmpeg errors into actionable fixes)
4. Visual verification (returns thumbnail after every operation)
5. Timeline DSL (declarative multi-track edits in one JSON)
6. Platform templates (TikTok/YouTube/Instagram presets)
7. 3 interfaces (MCP + Python client + CLI)

---

## Twitter/X Thread

---

**Tweet 1 (hook — competitive angle):**

I audited every video editing MCP server (there are 20+).

Most have 0 tests. None have progress reporting. All dump raw FFmpeg stderr when things fail.

So I built mcp-video — the one that actually works.

1074 tests collected. Progress callbacks. Auto-fix errors. Visual verification.

Here's what it does:

---

**Tweet 2 (demo):**

"Hey Claude, take this interview clip, trim it to 30 seconds, add a title card, resize for TikTok, and export."

That's it. One prompt. mcp-video handles the rest.

No FFmpeg flags to memorize. No cloud API to pay for. Your video never leaves your machine.

---

**Tweet 3 (differentiators):**

What makes mcp-video different from the 20+ other video MCP servers:

Progress callbacks — FFmpeg stderr parsed into real-time percentage
Auto-fix errors — "Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC"
Visual verification — thumbnail returned after every operation
1074 tests collected — the next closest competitor has 0

---

**Tweet 4 (tools):**

91 MCP tools, including:

video_info | video_trim | video_merge | video_add_text
video_add_audio | video_resize | video_convert | video_speed
video_thumbnail | video_preview | video_storyboard | video_subtitles
video_watermark | video_crop | video_rotate | video_fade
video_export | video_edit | video_extract_audio
hyperframes_init | hyperframes_render | search_tools
video_project_create | style_pack_read | storyboard_read | shot_prompt_render

Plus 5 platform templates: TikTok, YouTube Shorts, Reels, YouTube, Instagram Post.

---

**Tweet 5 (code):**

```python
from mcp_video import Client

editor = Client()
clip = editor.trim("v.mp4", start="0:30", duration="15")
final = editor.resize(clip.output_path, aspect_ratio="9:16")
result = editor.export(final.output_path, quality="high")
```

Also works as a CLI: `mcp-video trim video.mp4 -s 0:30 -d 15`

---

**Tweet 6 (CTA):**

pip install mcp-video

GitHub: github.com/KyaniteLabs/mcp-video
Apache 2.0. Contributions welcome.

If you build with MCP, I'd love to hear what tools you need.

---

## Hacker News Show HN Post

**Title:** Show HN: mcp-video - The video editing MCP server that actually works (1074 tests)

**Body:**

I audited 20+ video editing MCP servers before building mcp-video. Here's what I found:

- Most have 0 tests
- None report progress on long operations
- All dump raw FFmpeg stderr when things fail
- None have visual verification

mcp-video fixes all of these. It's an open-source MCP server that wraps FFmpeg, cinematic planning helpers, and Hyperframes into 91 structured tools with:

- **1074 tests collected** across the full testing pyramid (unit -> integration -> e2e)
- **Progress callbacks** — parses FFmpeg stderr in real-time, returns percentage (0-100) to the agent
- **Auto-fix error handling** — parses FFmpeg errors into structured responses with actionable suggestions ("Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC")
- **Visual verification** — returns a base64 thumbnail of the first frame after every operation, so agents can confirm results
- **Timeline DSL** — declarative multi-track edits (video + audio + text + transitions) in a single JSON object
- **Cinematic pre-production** — PUSHING CREATION-compatible style packs, storyboards, and shot-prompt expansion
- **5 platform templates** — TikTok, YouTube Shorts, Instagram Reel, YouTube, Instagram Post
- **3 interfaces** — MCP server, Python client, CLI

Three interfaces:
- MCP Server: Add to your config, then just tell your agent what to edit
- Python Client: Clean API for automation (`editor.trim("v.mp4", start="0:30", duration="15")`)
- CLI: `mcp-video trim video.mp4 -s 0:30 -d 15`

Quick setup:
```json
{
  "mcpServers": {
    "mcp-video": {
      "command": "uvx",
      "args": ["mcp-video"]
    }
  }
}
```

1074 tests collected. Pure Python. Core install only depends on mcp + pydantic + FFmpeg.

pip install mcp-video

GitHub: https://github.com/KyaniteLabs/mcp-video

---

## Reddit Posts

### r/MCP (Model Context Protocol)

**Title:** After trying 20+ video MCP servers, I built one that actually has tests

**Body:**

Hey everyone. I audited every video editing MCP server I could find before building mcp-video.

The state of the field: most have 0 tests, none report progress, all dump raw FFmpeg stderr, and none let agents verify results visually.

mcp-video fixes all of that:
- 1074 tests collected (unit, integration, e2e)
- Real-time progress callbacks (parses FFmpeg stderr)
- Auto-fix error handling (structured errors with suggested actions)
- Visual verification (thumbnail returned after every operation)
- Timeline DSL for complex multi-track edits
- 5 platform templates (TikTok, YouTube Shorts, etc.)
- Cinematic pre-production tools for style packs, storyboards, and shot prompts
- 3 interfaces: MCP server, Python client, CLI

Quick setup:
```json
{
  "mcpServers": {
    "mcp-video": {
      "command": "uvx",
      "args": ["mcp-video"]
    }
  }
}
```

Then: "Hey Claude, trim this video from 0:30 to 1:00 and add a title card."

91 tools. Apache 2.0.

What tools would you want to see in a video editing MCP server?

GitHub: https://github.com/KyaniteLabs/mcp-video

---

### r/ClaudeAI

**Title:** mcp-video — progress callbacks, visual verification, and 1074 tests for video editing in Claude Code

**Body:**

If you've ever wanted Claude to edit video for you, this is how.

mcp-video is an MCP server with 91 video editing and creation tools. What makes it different from the 20+ other video MCP servers:

1. **Progress callbacks** — Long operations (convert, merge, export) now report real-time progress. Your agent can tell you "50% done..." instead of going silent.

2. **Visual verification** — After every operation, mcp-video returns a thumbnail of the first frame. You can confirm the result looks right without opening the file.

3. **1074 tests collected** — The next closest competitor has 0.

4. **Auto-fix errors** — When FFmpeg fails, mcp-video parses the error and suggests a fix. "Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC".

Setup:
```json
{
  "mcpServers": {
    "mcp-video": { "command": "uvx", "args": ["mcp-video"] }
  }
}
```

Then: *"Take this interview clip, trim to 30 seconds, add 'EPISODE 1' as a title, and export for TikTok."*

Everything runs locally. No cloud, no API keys, no per-minute billing. Your video never leaves your machine.

pip install mcp-video

https://github.com/KyaniteLabs/mcp-video

---

### r/LocalLLaMA

**Title:** mcp-video — open source video editing MCP server (1074 tests, progress callbacks, works with Claude/Cursor)

**Body:**

Built an MCP server for video editing. After auditing 20+ competitors, I focused on what they all get wrong: tests, error handling, and progress reporting.

91 tools that wrap FFmpeg, cinematic planning helpers, and Hyperframes into a clean API for AI agents. Works with Claude Code, Cursor, and any MCP-compatible client.

What's different:
- 1074 tests collected (next closest competitor: 0)
- Progress callbacks (real-time FFmpeg stderr parsing)
- Auto-fix error handling (structured errors with suggested actions)
- Visual verification (thumbnail returned after operations)
- Timeline DSL for complex multi-track edits
- Cinematic pre-production tools for style packs, storyboards, and shot prompts
- Python client and CLI

1074 tests collected. Apache 2.0. pip install mcp-video.

https://github.com/KyaniteLabs/mcp-video

---

## Beta User Outreach DMs

### DM Template 1 (MCP builders)

Hey [Name], I saw you've been building with MCP and thought you might be interested — I just shipped mcp-video, an open-source video editing MCP server.

91 tools (trim, merge, text, audio, resize, crop, rotate, fade, convert, cinematic style packs/storyboards, Hyperframes render, and more) that work with Claude Code, Cursor, etc. It's the most tested video MCP server I'm aware of — 1074 tests collected, progress callbacks, auto-fix error handling.

Would love your feedback if you get a chance to try it. What video editing capabilities would be most useful in your workflows?

GitHub: https://github.com/KyaniteLabs/mcp-video

### DM Template 2 (AI content creators)

Hey [Name], I'm building mcp-video — an open-source tool that lets AI agents edit video. Think "FFmpeg but with an API that Claude can actually use."

The idea is you could tell Claude "take this podcast clip, trim to 60 seconds, add a subscribe CTA, and export for TikTok" and it just works.

Would you be interested in beta testing? Looking for people who edit video regularly and want to see how AI agents can help.

### DM Template 3 (Dev tool builders)

Hey [Name], been following your work on [their project]. I just built mcp-video — an MCP server for video editing.

The architecture is: MCP server wrapping FFmpeg, cinematic planning helpers, and Hyperframes, with a Python client and CLI. 91 tools, 1074 tests collected, progress callbacks, auto-fix errors, Apache 2.0.

Curious if you've thought about adding video capabilities to [their project]? Would be happy to collaborate or share what I've learned about the MCP tool-building patterns.

GitHub: https://github.com/KyaniteLabs/mcp-video
