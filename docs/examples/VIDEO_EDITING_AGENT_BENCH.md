# Video-Editing Agent Bench (TD.2 sketch)

Aider-style mechanic: fixed media + instruction set; agent must produce receipts.

## Suite (v0)

| Case | Instruction | Pass |
| --- | --- | --- |
| B1 | Trim to 5s from 0 | output duration ~5s + receipt |
| B2 | Burn SRT without drift | word timing test or review_run pass |
| B3 | Repurpose dry plan | intent plan / workflow plan JSON |
| B4 | Fail closed on missing file | InputFileError |
| B5 | Publish validate 9:16 | `video_publish_validate` pass/fail |

## Runner

```bash
kino estimate repurpose --duration 60 --format json
kino intent repurpose --format json
kino review-run path/to/out.mp4 --format json
```

Score = cases passed / cases total. Publish scores only with fixture SHAs.
