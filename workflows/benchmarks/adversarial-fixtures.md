# Adversarial Fixture Plan

Use these fixtures for a future `agentic-video-certify` command. Each fixture should either pass with a receipt or fail with a clear, actionable error.

Run the current local certification subset:

```bash
uv run --no-project --with kinocut python workflows/benchmarks/run_adversarial_certification.py
```

| Fixture | Purpose | Expected Behavior |
| --- | --- | --- |
| Silent video | Audio warnings should be explicit | Receipt records missing/quiet audio; human review required. |
| Very quiet audio | Loudness guardrail should fire | Quality recommendations include audio loudness issue. |
| Weird frame rate | Export path should normalize or warn | Receipt records source fps and output facts. |
| Vertical source to vertical output | Avoid unnecessary crop surprises | Output remains 9:16 and receipt records edit path. |
| Horizontal source to vertical output | Crop/resize is inspectable | Thumbnail/storyboard make framing reviewable. |
| Long filename with spaces | Path handling should be boring | Workflow completes without shell quoting failures. |
| Oversized caption | Text guardrails should prevent unsafe layout | Error or warning is clear before export. |
| Missing font | Font fallback should be clear | Workflow uses fallback or reports missing dependency. |
| Corrupted input | Failure should be early and readable | No partial publish artifact is treated as ready. |
| Unsupported codec | Doctor/ffprobe should identify blocker | Receipt or error names codec/container limitation. |

Start with synthetic media so the certification suite can run without private customer assets.
