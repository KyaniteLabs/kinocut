# Kinocut — Launch Posts

## Positioning

**Don't say:** "I built a video editing MCP server" (there are 20+).

**Do say:** "I built a local video-production surface for AI agents: editing, cinematic planning, rendering, and release checks without brittle FFmpeg prompting."

**Key differentiators:**
1. Structured tools across editing, planning, analysis, audio, effects, Hyperframes rendering, and local repurposing
2. Cinematic pre-production with style packs, storyboards, and shot-prompt expansion
3. Progress callbacks for long FFmpeg operations
4. Auto-fix error handling that turns FFmpeg failures into actionable fixes
5. Visual verification with thumbnails, storyboards, and release checkpoints
6. Timeline DSL and platform templates for repeatable social/video workflows
7. 3 interfaces: MCP server, Python client, and CLI

---

## Twitter/X Thread

---

**Tweet 1 (hook — competitive angle):**

AI agents can edit video, but raw FFmpeg prompting gets brittle fast.

So I built Kinocut: a local MCP server with structured video tools for editing, planning, rendering, and release checks.

Local tools. No cloud. No guessed FFmpeg flags.

Here's what it does:

---

**Tweet 2 (demo):**

"Hey Claude, take this interview clip, trim it to 30 seconds, add a title card, resize for TikTok, and export."

That's it. One prompt. Kinocut handles the rest.

No FFmpeg flags to memorize. No cloud API to pay for. Your video never leaves your machine.

---

**Tweet 3 (differentiators):**

What makes Kinocut different from the 20+ other video MCP servers:

Structured tools — editing, analysis, audio, effects, cinematic planning, Hyperframes rendering, and repurposing packages
Progress callbacks — FFmpeg stderr parsed into real-time percentage
Auto-fix errors — "Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC"
Visual verification — thumbnails, storyboards, and release checkpoints
Cinematic planning — style packs, storyboard tables, and shot prompts before generation

---

**Tweet 4 (tools):**

MCP tools include:

video_info | video_trim | video_merge | video_add_text
video_add_audio | video_resize | video_convert | video_speed
video_thumbnail | video_preview | video_storyboard | video_subtitles
video_watermark | video_crop | video_rotate | video_fade
video_export | video_edit | video_extract_audio
hyperframes_init | hyperframes_render | hyperframes_inspect | search_tools
video_project_create | style_pack_read | storyboard_read | shot_prompt_render
video_repurpose_plan | video_repurpose

Plus 5 platform templates: TikTok, YouTube Shorts, Reels, YouTube, Instagram Post.

---

**Tweet 5 (code):**

```python
from kinocut import Client

editor = Client()
clip = editor.trim("v.mp4", start="0:30", duration="15")
final = editor.resize(clip.output_path, aspect_ratio="9:16")
result = editor.export(final.output_path, quality="high")
```

Also works as a CLI: `kino trim video.mp4 -s 0:30 -d 15`

---

**Tweet 6 (CTA):**

pip install kinocut

Source: git.kyanitelabs.tech/KyaniteLabs/kinocut
Apache 2.0. Contributions welcome.

If you build with MCP, I'd love to hear what tools you need.

---

## Hacker News Show HN Post

**Title:** Show HN: Kinocut - Local video editing and planning tools for AI agents

**Body:**

Kinocut is an open-source MCP server that wraps FFmpeg, cinematic planning helpers, Hyperframes, and local repurposing into structured tools for agents:

- **Progress callbacks** — parses FFmpeg stderr in real-time, returns percentage (0-100) to the agent
- **Auto-fix error handling** — parses FFmpeg errors into structured responses with actionable suggestions ("Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC")
- **Visual verification** — returns a base64 thumbnail of the first frame after every operation, so agents can confirm results
- **Timeline DSL** — declarative multi-track edits (video + audio + text + transitions) in a single JSON object
- **Cinematic pre-production** — PUSHING CREATION-compatible style packs, storyboards, and shot-prompt expansion
- **Hyperframes authoring** — project scaffolds, renders, snapshots, layout inspection, catalog blocks, capture, local TTS, transcription, background removal, diagnostics, and benchmarks
- **Local repurposing** — platform variants with manifests, thumbnails, storyboards, and release-checkpoint artifacts
- **5 platform templates** — TikTok, YouTube Shorts, Instagram Reel, YouTube, Instagram Post
- **3 interfaces** — MCP server, Python client, CLI

Three interfaces:
- MCP Server: Add to your config, then just tell your agent what to edit
- Python Client: Clean API for automation (`editor.trim("v.mp4", start="0:30", duration="15")`)
- CLI: `kino trim video.mp4 -s 0:30 -d 15`
- CI-backed release process for package, registry, and repository readiness
- Listed on the [MCP Registry](https://registry.modelcontextprotocol.io/servers/io.github.KyaniteLabs/kinocut) (auto-published on release via `mcp-publisher`)

Quick setup:
```json
{
  "mcpServers": {
    "Kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

pip install kinocut

Source: https://git.kyanitelabs.tech/KyaniteLabs/kinocut

---

## Reddit Posts

### r/MCP (Model Context Protocol)

**Title:** Kinocut: local video editing, storyboards, and release checks for AI agents

**Body:**

Hey everyone. I built Kinocut because I wanted agents to edit video through structured operations instead of fragile one-off FFmpeg commands.

Kinocut gives agents:
- Structured tools for editing, analysis, effects, audio, cinematic planning, Hyperframes rendering, and repurposing packages
- Real-time progress callbacks (parses FFmpeg stderr)
- Auto-fix error handling (structured errors with suggested actions)
- Visual verification (thumbnail returned after every operation)
- Timeline DSL for complex multi-track edits
- 5 platform templates (TikTok, YouTube Shorts, etc.)
- Cinematic pre-production tools for style packs, storyboards, and shot prompts
- Hyperframes tools for snapshots, inspection, catalog blocks, capture, TTS, transcription, background removal, diagnostics, and benchmarks
- Repurposing tools for local Shorts, Reels, TikTok, and YouTube-style packages
- 3 interfaces: MCP server, Python client, CLI

Quick setup:
```json
{
  "mcpServers": {
    "Kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

Then: "Hey Claude, trim this video from 0:30 to 1:00 and add a title card."

Local tools. Apache 2.0.

What tools would you want to see in a video editing MCP server?

Source: https://git.kyanitelabs.tech/KyaniteLabs/kinocut

---

### r/ClaudeAI

**Title:** Kinocut — local video editing, planning, and release checks in Claude Code

**Body:**

If you've ever wanted Claude to edit video for you, this is how.

Kinocut is an MCP server with local video editing and creation tools:

1. **Progress callbacks** — Long operations (convert, merge, export) now report real-time progress. Your agent can tell you "50% done..." instead of going silent.

2. **Visual verification** — After every operation, Kinocut returns a thumbnail of the first frame. You can confirm the result looks right without opening the file.

3. **Cinematic planning** — Style packs, storyboard tables, and shot prompts help plan generated video before rendering.

4. **Auto-fix errors** — When FFmpeg fails, Kinocut parses the error and suggests a fix. "Codec error: vp9" → "Auto-convert from vp9 to H.264/AAC".

Setup:
```json
{
  "mcpServers": {
    "Kinocut": { "command": "uvx", "args": ["--from", "kinocut", "kino"] }
  }
}
```

Then: *"Take this interview clip, trim to 30 seconds, add 'EPISODE 1' as a title, and export for TikTok."*

Everything runs locally. No cloud, no API keys, no per-minute billing. Your video never leaves your machine.

pip install kinocut

https://git.kyanitelabs.tech/KyaniteLabs/kinocut

---

### r/LocalLLaMA

**Title:** Kinocut — open source video editing MCP server with planning and release checks

**Body:**

Built an MCP server for local video editing and planning. The goal is to give agents structured media operations instead of raw shell-command improvisation.

Structured tools that wrap FFmpeg, cinematic planning helpers, Hyperframes, and local repurposing into a clean API for AI agents. Works with Claude Code, Cursor, and any MCP-compatible client.

What's different:
- Progress callbacks (real-time FFmpeg stderr parsing)
- Auto-fix error handling (structured errors with suggested actions)
- Visual verification (thumbnail returned after operations)
- Timeline DSL for complex multi-track edits
- Cinematic pre-production tools for style packs, storyboards, and shot prompts
- Hyperframes tools for renders, snapshots, inspection, catalog blocks, capture, local TTS, transcription, background removal, diagnostics, and benchmarks
- Repurposing tools for platform-ready local packages
- Python client and CLI

Apache 2.0. pip install kinocut.

https://git.kyanitelabs.tech/KyaniteLabs/kinocut

---

## Beta User Outreach DMs

### DM Template 1 (MCP builders)

Hey [Name], I saw you've been building with MCP and thought you might be interested — I just shipped Kinocut, an open-source video editing MCP server.

Structured tools (trim, merge, text, audio, resize, crop, rotate, fade, convert, cinematic style packs/storyboards, Hyperframes render/inspect/capture/TTS/background removal, repurposing packages, and more) that work with Claude Code, Cursor, etc. The useful part is that agents get structured operations, progress callbacks, visual review artifacts, and actionable FFmpeg errors.

Would love your feedback if you get a chance to try it. What video editing capabilities would be most useful in your workflows?

Source: https://git.kyanitelabs.tech/KyaniteLabs/kinocut

### DM Template 2 (AI content creators)

Hey [Name], I'm building Kinocut — an open-source tool that lets AI agents edit video. Think "FFmpeg but with an API that Claude can actually use."

The idea is you could tell Claude "take this podcast clip, trim to 60 seconds, add a subscribe CTA, and export for TikTok" and it just works.

Would you be interested in beta testing? Looking for people who edit video regularly and want to see how AI agents can help.

### DM Template 3 (Dev tool builders)

Hey [Name], been following your work on [their project]. I just built Kinocut — an MCP server for video editing.

The architecture is: MCP server wrapping FFmpeg, cinematic planning helpers, Hyperframes, and local repurposing, with a Python client and CLI. Structured operations, progress callbacks, auto-fix errors, visual review artifacts, Apache 2.0.

Curious if you've thought about adding video capabilities to [their project]? Would be happy to collaborate or share what I've learned about the MCP tool-building patterns.

Source: https://git.kyanitelabs.tech/KyaniteLabs/kinocut
