# MCP Video Proof Gallery

This directory collects dated proof artifacts for mcp-video confidence work.

## Current Proofs

| Date | Artifact | Purpose |
| --- | --- | --- |
| 2026-07-10 | [MCP Video 1.6.0 rescue and post-rescue receipt](release-1.6.0/RESCUE_POST_RESCUE_RECEIPT.md) | Current release-candidate scope, requirement map, verification gates, issue receipts, and compatibility boundaries. |
| 2026-06-03 | [Fresh install confidence baseline](2026-06-03-fresh-install-confidence-baseline.md) | Proves published `mcp-video` can install, diagnose, edit, quality-check, and checkpoint a tiny generated video. |
| 2026-06-03 | [Public issue triage](2026-06-03-public-issue-triage.md) | Separates real repo-health follow-up from stale pipeline/dashboard issues. |
| 2026-06-03 | [Agentic media readiness report](2026-06-03-agentic-media-readiness-report.md) | Customer-facing summary of what is proven, what is still manual, and what should be verified next. |
| 2026-06-03 | [External feedback ask](2026-06-03-external-feedback-ask.md) | Ready-to-send request for technical builders to test the first workflow. |

## Proof Rules

- Every publishable media proof should include a Video Receipt.
- Keep raw/generated media out of git unless intentionally curated as a public demo asset.
- Record exact commands and environment details when a proof depends on local state.
- Keep stale automation findings separate from current product readiness.
