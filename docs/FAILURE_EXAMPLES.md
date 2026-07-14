# Failure-as-feature examples

Kinocut is designed to **stop bad renders early**. These examples show failures you should treat as product behavior, not bugs.

## 1. Preflight: risky filter parameter

**Intent:** blur far beyond a sane range.  
**Expected:** validation / guardrail error before FFmpeg produces unusable output.

```python
from kinocut import Client
from kinocut.errors import MCPVideoError

c = Client()
try:
    c.filter("in.mp4", filter_type="blur", intensity=9999)  # out of range
except MCPVideoError as e:
    print(e.error_type, e)  # structured, actionable
```

**Teach agents:** parse structured errors; do not retry with the same illegal value.

## 2. Merge incompatibility

**Intent:** concat clips with mismatched streams without auto-normalize path.  
**Expected:** merge-compatibility guardrail warns or fails closed with guidance.

```python
# Prefer explicit convert/resize to a common profile, then merge —
# or use merge paths that document auto-normalize behavior.
```

**Teach agents:** probe both sources (`info`) before merge; normalize resolution/fps/sample rate first.

## 3. Workflow unsafe path

**Intent:** workflow step points at a path outside the workspace.  
**Expected:** `unsafe_workflow_source` (or equivalent) — no write outside confinement.

```bash
kino workflow-validate --spec bad-job.json
# fails closed on escaping @refs / absolute out-of-workspace paths
```

## 4. Quality gate hold

**Intent:** export a clip that fails automated quality.  
**Expected:** `quality_check` / `release_checkpoint` reports `all_passed: false` or score below `min_score`; receipt still records the attempt.

```python
result = c.quality_check("final.mp4")
# result["all_passed"] may be False — do not publish; open recommendations
```

**Teach agents:** low score is a **stop for human review**, not a silent continue.

## 5. Rescue without approval

**Intent:** render rescue repairs without approved safe IDs.  
**Expected:** fail closed — source stays immutable until plan + approval.

See [RESCUE.md](RESCUE.md).

## 6. Governed AI-video without human evidence (dev tip)

**Intent:** approve a verdict with analyzer-only output.  
**Expected:** approval rejected — exact human decision evidence required.

See [AI_VIDEO_REVIEW_AND_SALVAGE.md](AI_VIDEO_REVIEW_AND_SALVAGE.md).

## Receipt after failure

Even failed or partial runs should leave inspectable state when a receipt/plan was requested (workflow resume cursor, rescue package, quality JSON). Prefer tools that return structured `success: false` over swallowing stderr.

## Related

- [VIDEO_RECEIPT.md](VIDEO_RECEIPT.md)
- [GOLDEN_PATH.md](GOLDEN_PATH.md)
- [WORKFLOWS.md](WORKFLOWS.md)
