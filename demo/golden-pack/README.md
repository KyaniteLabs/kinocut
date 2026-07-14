# Golden demo pack

Shareable first-run proof for Kinocut: synthetic source → vertical captioned clip → quality gate → **Video Receipt**.

## Regenerate (local)

Requires FFmpeg and a working Kinocut install (`pip install -e .` from repo root).

```bash
python scripts/golden_path.py
python scripts/generate_golden_pack.py --skip-run
```

## Layout

| Path | In git? | Purpose |
| --- | --- | --- |
| `sample_video_receipt.json` | yes | Curated/shareable receipt sample (paths relativized when generated) |
| `artifacts/` | no (media gitignored) | Full pack: receipt, quality, checkpoint, mp4s after generate |
| `README.md` | yes | This file |

## What to show people

1. `kino doctor` green  
2. `final_clip.mp4`  
3. `video_receipt.json` — tools run, quality, `human_review.status: pending`  

This pack proves **plumbing and the trust model**, not creative excellence. Synthetic source media is intentional.

## Site / social

Link: “Run the [golden path](../../docs/GOLDEN_PATH.md)” and attach or re-run the pack locally rather than committing large binaries.
