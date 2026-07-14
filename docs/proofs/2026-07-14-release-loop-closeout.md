# Kinocut 1.8 release-loop closeout

**Date:** 2026-07-14  
**Candidate branch:** `docs/1.8-freshness-pass`

This receipt covers the final documentation reconciliation and the publish-workflow
idempotency fix. It does not replace the original Kinocut 1.8.0 publication receipt.

## Closed loops

- Duplicate `release.published` events no longer fail merely because the exact PyPI
  or npm version already exists; downstream publishers retain their existing
  skip/verification behavior.
- Release and recovery dispatches share one non-cancelling concurrency group, removing
  the observed npm publication race.
- The final TasteCheck status now records the completed production keyboard, cold-load,
  and responsive-overflow checks. The earlier HOLD ledger is explicitly historical.

## Verification

- Regression contract was observed failing before the workflow change and passing after it.
- Targeted release/documentation tests: `10 passed`.
- Repository readiness audit: passed; its only warning was the expected uncommitted
  candidate diff.
- Compatibility import: `kinocut.Client is mcp_video.Client` passed.
- Full repository gate: `3819 passed, 170 skipped, 10 warnings` in `883.20s`;
  command exit code `0`.

The warnings were the repository's expected timeout-mark, guardrail, and synthetic-media
warnings; there were no test failures.
