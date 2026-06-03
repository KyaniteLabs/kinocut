# Video Receipt

A Video Receipt is the trust artifact for an agentic media workflow. It records what the user asked for, what media was inspected, which tools ran, what changed, which guardrails fired, and what still needs human review.

Use it when a workflow creates or edits media that may be published, handed to a client, or used as proof.

## Required Fields

```json
{
  "user_intent": "Turn a source clip into a captioned vertical short.",
  "source_media": {
    "path": "output/source.mp4",
    "duration_seconds": 6.0,
    "width": 1280,
    "height": 720
  },
  "tool_calls": [
    {
      "stage": "01-trim",
      "tool": "Client.trim",
      "output": "output/01_trimmed.mp4"
    }
  ],
  "edits_applied": [
    "trimmed source clip",
    "resized to 9:16",
    "added hook text",
    "normalized audio",
    "exported final MP4"
  ],
  "guardrails_triggered": [],
  "quality": {
    "all_passed": true,
    "overall_score": 70.3,
    "recommendations": []
  },
  "review_artifacts": {
    "final_video": "output/final_clip.mp4",
    "thumbnail": "output/checkpoint/thumbnail.jpg",
    "storyboard": [
      "output/checkpoint/storyboard/frame_01.jpg",
      "output/checkpoint/storyboard/frame_02.jpg"
    ]
  },
  "human_review": {
    "required": true,
    "status": "pending",
    "instructions": "Open the final video, thumbnail, and storyboard before publishing."
  },
  "known_limitations": [
    "Automated quality checks do not replace visual/audio review."
  ],
  "next_edit_suggestion": "Adjust hook text and rerun release checkpoint after human review."
}
```

## Trust Rules

- Do not treat a rendered video as publishable until a receipt exists.
- Do not hide quality warnings. Warnings are part of the proof.
- Do not overwrite source media.
- Do not mark human review complete automatically.
- Keep generated videos, thumbnails, and storyboards out of git unless they are intentionally curated release/demo assets.

## Local Verification

Use the confidence benchmark to check that a workflow produced the expected receipt and review artifacts:

```bash
uv run --no-project --with mcp-video python workflows/benchmarks/run_confidence_benchmark.py
```

The benchmark is intentionally narrow: it proves the receipt-backed baseline can run and that the final video, quality report, release checkpoint, thumbnail, storyboard frames, and human-review state are present.
