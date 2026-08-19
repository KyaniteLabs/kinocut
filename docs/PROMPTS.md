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

## 1b. Product / object matte onto a shop plate

```text
Using Kinocut only (no raw FFmpeg shell, no new tool name):
1) kino --format json hyperframes-remove-background --info
   Confirm default model is people and birefnet-general is products-and-objects.
2) If the object extra is missing, stop and tell me to pip install "kinocut[object-matte]".
   Do not run the people model on a product turntable.
3) Cut ABS_PATH/turntable.mp4 with --model birefnet-general --mask-interval 3
   to a cutout next to a composite-layers spec directory.
4) Dry-run composite-layers with spec-dir-relative src only (see examples/product-matte/).
5) quality_check. Human review before any shop publish.
Follow docs/PRODUCT_MATTE.md.
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

## 6. 360 dual-cam assembly (master tip)

```text
Using Kinocut only (no Insta360 Studio, no raw FFmpeg):
Source is a stitched 360 MP4 at ABS_PATH/x4-export.mp4 (not .insv).
1) kino doctor (note optional sphere_director)
2) Propose via video_intent goal="desk 360 split 9:16" source=ABS_PATH/x4-export.mp4
   or Client.propose_360_assembly(..., storyboard_dir=ABS_PATH/board)
3) Show cameras, layout, and stills. Wait for my approve or reject.
4) Only after approve: render 9:16 split. Do not render a proposed plan.
5) quality_check / receipt. Human review still pending.
If the file is .insv or not equirect, report the structured error and stop.
```

## 7. Preflight failure drill

```text
Deliberately call a Kinocut edit with an illegal parameter (e.g. extreme filter intensity).
Show the structured error. Explain how you would correct the call.
Do not fall back to raw shell FFmpeg.
```

## 8. Quality gate hold

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
