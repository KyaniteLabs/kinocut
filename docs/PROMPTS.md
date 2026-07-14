# Prompt library (agent paste)

Deterministic-leaning prompts for Claude Code, Cursor, and other MCP hosts with Kinocut connected.  
Prefer **absolute paths**. Always end with quality/receipt and human review.

## 0. Golden path (repo clone)

```text
From the Kinocut repo root, run the golden path:
1) kino doctor
2) python scripts/golden_path.py
3) Open workflows/05-confidence-baseline/output/video_receipt.json and summarize tool_calls, quality, and human_review.
Do not publish the clip.
```

## 1. Captioned vertical short

```text
Using Kinocut tools only (no raw FFmpeg shell):
1) Probe ABS_PATH/interview.mp4
2) Trim the strongest ~45s starting near 00:02:00 (adjust if duration is shorter)
3) Transcribe if whisper extra is available; otherwise skip captions and note the limitation
4) Burn captions if an SRT exists
5) Resize to 9:16
6) Normalize audio to about -14 LUFS
7) quality_check + release_checkpoint
8) Write a short Video Receipt summary (intent, tools, quality, human_review pending)
Do not claim publish-ready without human review.
```

## 2. Podcast highlight package

```text
Local podcast file ABS_PATH/episode.mp4:
- Find a strong 60s segment (or use start=00:05:00 if no semantic tools)
- Trim, normalize audio, add chapter-style title text once
- Export MP4 + quality_check
- List remaining human review items (hook, title accuracy)
```

## 3. Repurpose dry-run then render

```text
Plan a repurpose package for ABS_PATH/master.mp4 for youtube-shorts and tiktok.
First run a dry-run / plan only and show the manifest.
After I approve, render local variants with thumbnails and a receipt.
Do not upload anywhere.
```

## 4. Rescue (content-preserving)

```text
Use Kinocut rescue tools on ABS_PATH/damaged.mp4:
1) rescue plan / inspect diagnosis
2) Propose only safe repair IDs
3) Wait for my explicit approval list
4) Render and inspect the package
Keep the source immutable. Explain any unavailable caption sidecars.
```

## 5. Workflow engine job

```text
Create a workflow job.json that: probes a source, trims 6s, resizes 1080x1920, adds text "Watch this".
Run workflow-validate, workflow-plan, then workflow-render with a saved receipt.
Inspect the receipt hashes and resume cursor.
```

## 6. Preflight failure drill

```text
Deliberately call a Kinocut edit with an illegal parameter (e.g. extreme filter intensity).
Show the structured error. Explain how you would correct the call.
Do not fall back to raw shell FFmpeg.
```

## 7. Quality gate hold

```text
Run quality_check on ABS_PATH/export.mp4 with fail-on-warning if available.
If all_passed is false, list recommendations and stop before any publish language.
```

## Config paste (Cursor / MCP JSON)

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

Claude Code:

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

## Skills

```text
Use the $kinocut skill for inspect → edit → verify → human review.
For short-form packages from current tools only, use the kinocut-repurpose skill; do not invent CLI flags.
```
