# AI-video and sound program: draft PR status

> **Successor status:** This historical Wave-3 checkpoint is superseded by
> [`2026-07-12-ready-units-integration-checkpoint.md`](2026-07-12-ready-units-integration-checkpoint.md),
> which records the reviewed audio, registry, subtitle, graphics, and `kinocut_sound` foundation
> integration at `090424c`. It is pre-release evidence and does not override the
> published 1.8.0 release state.

**Snapshot date:** 2026-07-12

**Current reviewed implementation tip:** `46e5e0d84b6e0d325e226c540e3384dbee3ef0b0`

**Hygiene tip:** `47731e9`

**G006 remediation checkpoint:** `7d16d525121f5bf8e9e427798304e89057844051` (reviewed implementation tip); hygiene closeout `47731e9`

**State:** G006 local gates green; awaiting exact-tip remote CI; not released

## Executive summary

The branch contains the contract and project-store foundation, the first field-safety fixes,
deterministic ingest/inspection, and a governed Wave 3 review-and-salvage surface with the G006
evidence-integrity blockers closed. The current successor passes the complete local gate and is
awaiting exact-tip remote CI. It is a bounded merge candidate, not a release candidate.

The checkpoint must remain unreleased. It does not authorize a version bump, tag, package upload,
registry submission, deployment, release creation, or announcement.

## Implemented in the snapshot

- Strict AI-video contracts, canonical IDs, append-only private project storage, migrations,
  privacy boundaries, capability records, and receipt sections.
- Loss-proof add-audio duration policy and ASS/dimension-aware subtitle handling.
- Content-addressed ingest with generation lineage and usage-rights metadata.
- Unified media preflight, deterministic temporal inspection artifacts, defect checks, and
  optional visual findings that fail soft.
- Editorial verdicts, acceptance evaluation, protected-element checks, audio-preserving body
  swap, lineage-bound salvage derivatives, and MCP/Python/CLI surfaces.
- Store-identity and exact-human-acceptance hardening at the snapshot head.

## G006 closeout — Wave 3 evidence-integrity blockers resolved

The three G006 blockers are closed on the reviewed implementation branch at tip
`7d16d525121f5bf8e9e427798304e89057844051` (hygiene tip `47731e9`):

- `c80c579` — `trim_audio` proof binds the output audio to a bounded prefix of the approved source.
- `a3b51fc` — region-crop, still-frame, and full freeze-prefix/tail/extension origin checks bind
  the entire salvage frame range to the descriptor. `BACKGROUND_ONLY` uses the existing 3-frame
  `_crop_origin_check` (start/mid/end), noted as a defense-in-depth limitation — only three
  representative frames are verified, not every frame — without reopening the scoped G006 blocker.
- `345c2dc` — `mutation_fingerprint` and `authorization_decision_ids` are persisted in the v2
  salvage-lineage manifest; replay rejects tampered, stale, or superseded authorization.
- `7d16d52` — the salvage authorization resolver is unified with the protection gate so that
  `target_ref` binding is enforced identically on initial render and lineage replay.

### Review verdicts and whole-gate evidence

- **Architecture review:** APPROVE — 279 focused pass.
- **Security review:** CLEAR — 102 + 57 focused pass (security/source/body-swap/salvage suite).
- **Body-swap focused tests:** 22 (not 24).
- **Whole repository suite on the reviewed implementation tip:** 3088 passed, 18 skipped, 8
  warnings, 552.04s.
- **Import/diff/forbidden/readiness/leak gates:** all recorded as pass on the reviewed tip (import
  alias, `git diff --check`, forbidden-artifact scan, repository-readiness audit, gitleaks
  working-tree scan).

### Forgejo CI compatibility successor

Forgejo run 142 on the older publication tip `411bc529` was present and failed: 6 failed, 2936
passed, 13 skipped. Its Debian/root/FFmpeg 5 runner exposed two environment-dependent defects:
verified source snapshots remained writable to root, and FFmpeg 5 `showinfo` output omitted
`duration_time`, preventing corrupt-frame evidence from being emitted.

Commit `46e5e0d` closes both defects. Verified snapshots now use immutable Linux memfd seals and
fail closed when sealing is unavailable. Temporal diagnostics parse FFmpeg 5 output, reject
filename/banner/component false positives, and clamp fallback frame intervals to the expected
media end. Evidence on the successor tip:

- exact Debian/root/FFmpeg 5 reproductions: 22 passed;
- independent code/security/architecture review: APPROVE / CLEAR, 49 focused passed;
- whole repository suite in the recorded validation environment: 3104 passed, 18 skipped, 8 warnings, 536.51s;
- Ruff, canonical import alias, diff hygiene, forbidden-artifact scan, and public leak scan: pass.

The successor must still receive a green exact-tip Forgejo run before merge. Platforms without
Linux immutable memfd seals cannot perform verified snapshot-backed operations; those operations
fail closed rather than silently accepting mutable evidence.

This is a merge-ready bounded checkpoint for Wave 3. It is **not** release-ready, publish-ready, or
deploy-ready. The explicit stop-before-release gate remains in force: no tag, package, deploy,
announcement, or release creation is authorized. Human visual/audio review of any generated media
is a separate required decision that no automated receipt satisfies.

Later waves (4–10, Sound, Kernel) remain open and are not claimed as complete by this checkpoint.

## Program state after Wave 3

The remaining program includes audio continuity, subtitle/graphics QA, asset intelligence,
editorial planning, review and approval, agent ergonomics, learning/benchmarking, and the
standalone-capable `kinocut_sound` module. The protected-timeline kernel integration remains
blocked until its named upstream kernel contract exists and a human explicitly removes the gate.

See [the parallel execution plan](../plans/2026-07-12-wishlist-parallel-execution.md) for the
dependency graph, ownership boundaries, merge order, and final stop-before-release gate.

## Review rules for this draft

1. Merge this bounded Wave 3 checkpoint only after its exact-tip gates pass; keep every follow-on wave in a separate reviewed change unit.
2. Split follow-on implementation into bounded, independently reviewed change units.
3. Keep controller-owned public registries, schemas, defaults, CLI dispatch, and documentation
   joins serialized.
4. Never infer publication readiness from passing automation. Human visual/audio review is a
   separate required decision.
5. Keep the release stop in force after program verification until explicit release authority is
   granted.
