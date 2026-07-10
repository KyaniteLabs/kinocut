# Example workflow — captioned vertical short

A runnable [agent workflow engine](../../../docs/WORKFLOWS.md) job-spec: probe a source
clip, trim it, make it vertical, burn a caption, and prove the run with a receipt. It also
declares a `square` batch variant.

[`job.json`](job.json) uses only allowlisted ops (`probe`, `trim`, `resize`, `add_text`)
and **workspace-relative** paths, so every artifact stays free of home paths, usernames,
or tokens.

## Layout

Run from this directory (it is the spec's workspace root). Provide your own source clip:

```
captioned-vertical-short/
  job.json          # this spec
  input/hero.mp4    # your source clip (not committed)
  output/           # final.mp4 (and final.square.mp4 for the variant) land here
  work/             # per-run intermediates, auto-cleaned on success
```

## Run it

```bash
# 1. cheap structural gate (also test-merges the square variant), no render
kino workflow-validate --spec job.json

# 2. dry-run plan: op graph + source probes/hashes, renders zero media
kino workflow-plan --spec job.json --save-plan plan.json

# 3. execute + write a provenance receipt
kino workflow-render --spec job.json --save-receipt receipt.json

# 4. render the square variant too (each variant into its own receipt)
kino workflow-render --spec job.json --all-variants --save-receipt-dir receipts/

# 5. summarize any receipt (read-only integrity re-check)
kino workflow-inspect --receipt receipt.json
```

Python:

```python
from kinocut import Client

video = Client()
video.workflow_validate("job.json")
video.workflow_plan("job.json", save_plan="plan.json")
receipt = video.workflow_render("job.json", save_receipt="receipt.json")
print(receipt["status"], receipt["outputs"][0]["path"])
```

If a render fails, its intermediates are kept so you can fix the cause and resume:

```bash
kino workflow-render --spec job.json --resume receipt.json --save-receipt receipt.json
```

Receipt shapes are documented in [VIDEO_RECEIPT.md](../../../docs/VIDEO_RECEIPT.md).
