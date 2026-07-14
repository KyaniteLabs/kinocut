# Ready-units integration checkpoint

**Snapshot date:** 2026-07-12

> **Historical pre-release snapshot:** This checkpoint predates the published 1.8.0
> release and is retained as implementation evidence, not current release guidance.

**Reviewed implementation tip:** `090424c`

**State:** local integration gates green in the recorded validation environment; independently approved; unreleased at the snapshot date

## Executive summary

This checkpoint integrates the first post-Wave-3 capability units without crossing the release
boundary. It adds governed audio-bed composition, voice seam analysis, approved-asset registry
queries, subtitle QA, deterministic graphics recipes, and the standalone `kinocut_sound`
foundation. The final review remediation is committed at `090424c`.

This is a merge checkpoint, not a release candidate. It authorizes no version bump, tag, package
upload, registry submission, deployment, release creation, or announcement.

## Integrated capability units

- Governed one-shot audio-bed parameters and receipts, including exact duration policy, fades,
  normalization, ducking, source snapshots, and mix-volume identity.
- Voice-style and voice-identity seam analysis with EOF-clamped timestamps, strict numeric bounds,
  fail-soft provider handling, and provider-result revalidation.
- Active approved clip and reusable-bed registry queries with verdict, rights, supersession,
  source-asset, and typed-pagination enforcement.
- Subtitle temporal and safe-area QA with strict cue, profile, threshold, target, and actor
  validation.
- Deterministic graphics recipes whose mutation authorization and receipt identity bind source
  assets, fonts, parameters, and authorization decisions.
- Standalone `kinocut_sound` foundation contracts for plans, timelines, routing, delivery,
  consent, receipts, capabilities, and render fingerprints.
- Distribution metadata that includes `kinocut_sound` in both wheel and source archives.

## Verification receipt

- Full repository suite: **3506 passed, 18 skipped, 8 warnings in 599.97s**.
- Focused remediation suite: **213 passed in 35.33s**.
- Canonical import compatibility:
  `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"` — pass.
- Ruff on every changed Python file — pass.
- `git diff --check` and forbidden-artifact scan — pass.
- Repository-readiness architecture checks — pass; pre-push audit reports only the expected new
  branch-without-upstream condition.
- Public leak audit — pass. Matches were limited to deliberate hostile-input fixtures and redacted
  placeholders; no real username, home path, host address, email, credential, or token is present.
- Wheel and source build — pass; each archive contains 16 `kinocut_sound` files.
- Independent architecture review — **APPROVE**.
- Independent security review — **APPROVE**.

## Remaining program boundary

The full wishlist remains open beyond this bounded checkpoint. Remaining work includes deeper
asset intelligence, editorial planning, review/approval workflows, CLI and agent ergonomics,
learning and benchmark surfaces, and `kinocut_sound` voice, post/spatial, assembly, ambience,
voice-management, QA, orchestration, scalability, episode-rendering, benchmark, and final Kinocut
adapter units.

The protected-timeline kernel remains separately gated by its named upstream contract and an
explicit human decision. No substitute kernel is authorized.

## Release stop

After merge, continue implementation from the updated open-loop ledger. Stop again before any
version bump, tag, upload, deployment, release, or announcement and request explicit authority.
