# Tutorial: podcast → vertical shorts with a receipt

**Canonical first tutorial for Kinocut.** Local-only. No uploads. Human review required before publish.

## You will produce

- One or more vertical clips from a local podcast/interview file  
- Optional captions if Whisper extra is installed  
- `quality` / checkpoint artifacts  
- A Video Receipt summary (intent, tools, pending human review)

## Prerequisites

```bash
brew install ffmpeg   # or apt
pip install kinocut
kino doctor
# optional captions:
# pip install "kinocut[transcribe]"
```

Connect MCP (optional):

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

## Path A — Agent (recommended)

Paste into Claude Code / Cursor with Kinocut MCP enabled:

```text
Local file: ABS_PATH/episode.mp4
Using Kinocut only:
1) Probe duration and streams
2) Trim a strong ~45–60s segment (or start=00:05:00 if unsure)
3) If transcription is available, create an SRT and burn captions; else skip and note why
4) Resize to 9:16
5) Normalize audio (~ -14 LUFS)
6) quality_check + release_checkpoint
7) Summarize a Video Receipt: intent, tool_calls, quality, human_review pending
Do not upload or claim publish-ready.
```

More prompts: [PROMPTS.md](PROMPTS.md).

## Path B — Python client

```python
from kinocut import Client

c = Client()
src = "/ABS/PATH/episode.mp4"
clip = c.trim(src, start="00:05:00", duration="00:00:45")
# optional: c.ai_transcribe(...); c.subtitles(...)
vert = c.resize(clip.output_path, aspect_ratio="9:16")
norm = c.normalize_audio(vert.output_path, target_lufs=-14.0)
final = c.convert(norm.output_path, format="mp4", quality="high")
print(c.quality_check(final.output_path))
print(c.release_checkpoint(final.output_path, min_score=50))
```

## Path C — Golden plumbing proof (no private media)

```bash
python scripts/golden_path.py
```

## Path D — Workflow engine

Use a job spec (`probe` → `trim` → `resize` → `add_text`) with `workflow-validate` / `plan` / `render` / `inspect`.  
See [WORKFLOWS.md](WORKFLOWS.md) and `examples/workflows/captioned-vertical-short/`.

## Human review checklist

- [ ] Hook is clear in first 2 seconds  
- [ ] Captions accurate (if any)  
- [ ] Loudness comfortable  
- [ ] No bad crop on faces  
- [ ] Receipt matches what you intended  

## Related

- [VIDEO_RECEIPT.md](VIDEO_RECEIPT.md)  
- [INSTALL.md](INSTALL.md)  
- [demo/golden-pack](../demo/golden-pack/README.md)  
