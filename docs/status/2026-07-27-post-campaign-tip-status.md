# Kinocut post-campaign tip status

**Truth date:** 2026-07-27  
**Published release:** 1.11.1 (161 MCP tools / 140 CLI commands)  
**Development tip:** 164 MCP tools / 140 CLI commands  
**Release authority:** none implied by this document

## What is implemented on `master`

- Durable edit projects under `kinocut/projectstore/`, including
  content-addressed assets, async render jobs, kill/reopen/resume, ordered events,
  receipt lineage, semantic selections, and reusable project recipes.
- Kernel-backed repurposing that wraps the existing `video_workflow_*` engine.
  The durable layer does not rebuild or replace that engine.
- Rendered acceptance paths for durable repurposing, reviewed highlight
  selections, speaker-aware vertical reframe, word-timed styled captions,
  disfluency-cut compilation, and recipe export/replay.
- Project-store security threat model and deterministic adversarial guards.
- Alpha-aware layered compositing with masks, transforms, blend modes, per-layer
  effect routing, and real-render determinism checks.
- Repository-owned CI runner image/topology contract and native MCPB supply-chain
  foundations.

These are development-tip facts, not a claim that a package newer than 1.11.1
has been released.

## What remains human or externally gated

- Phase 3 watching-guardrail issues #73–78 and Phase 4 multiplier issues #79–82
  retain their explicit post-release gates.
- Trusted-execution expansion issues #95–107 retain their explicit post-release
  gates.
- Native MCPB still needs accepted four-platform runtime locks, clean-machine
  builds, licensing/source bundles, signing decisions, official validation and
  pack evidence, and human release review.
- Forgejo runner activation still needs a working image build/publish path,
  administrator label mapping, and observed push/PR runs.
- Production stream-to-shorts claims still need the G004 human listening,
  phone-frame, and multi-minute fixture evidence.
- Directory submissions, tags, package uploads, signing, public deployment, and
  real-user-program claims require separate human authority or real evidence.

## Verification

The compositor closeout completed with **4702 passed / 171 skipped** locally.
Forgejo required checks passed for standard tests, slow tests, lint, and the
FFmpeg 6/7/8 matrix before merge. Issues #34–36 closed after that merge.

For machine-readable published-versus-tip counts, use
[`docs/public_claims.json`](../public_claims.json).
