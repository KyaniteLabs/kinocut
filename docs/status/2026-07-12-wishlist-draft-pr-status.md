# AI-video and sound program: draft PR status

**Snapshot date:** 2026-07-12

**Implementation head reviewed for this snapshot:** `c88f8efa21709d5d073ddab6667ffa3def64ee4f`

**Documentation-complete integration head verified:** `7911d1ed10ebbc047356a525d8980b29a7962fa1`

**State:** draft review only; incomplete; not released

## Executive summary

The branch contains the contract and project-store foundation, the first field-safety fixes,
deterministic ingest/inspection, and an initial governed Wave 3 review-and-salvage surface. It is
ready to be exposed as a **draft, do-not-merge review snapshot**, not as a release candidate.

The draft must remain unreleased. It does not authorize a version bump, tag, package upload,
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

## Still open before Wave 3 is complete

- Finish the current independent review and close every remaining protection, source-snapshot,
  audio-preservation, and recipe-specific salvage finding.
- Re-run the complete repository gate on the final integrated source and attach immutable
  receipts; earlier task-local reports are not current-branch proof.
- Test and quality-guardrail modules were decomposed below the 800-line repository limit; retain
  the architecture/size gate on every downstream integration.
- Obtain an independent security/architecture review of the frozen Wave 3 tip.

## Program state after Wave 3

The remaining program includes audio continuity, subtitle/graphics QA, asset intelligence,
editorial planning, review and approval, agent ergonomics, learning/benchmarking, and the
standalone-capable `kinocut_sound` module. The protected-timeline kernel integration remains
blocked until its named upstream kernel contract exists and a human explicitly removes the gate.

See [the parallel execution plan](../plans/2026-07-12-wishlist-parallel-execution.md) for the
dependency graph, ownership boundaries, merge order, and final stop-before-release gate.

## Review rules for this draft

1. Treat the PR as an umbrella snapshot for early review; do not merge it as one giant unit.
2. Split follow-on implementation into bounded, independently reviewed change units.
3. Keep controller-owned public registries, schemas, defaults, CLI dispatch, and documentation
   joins serialized.
4. Never infer publication readiness from passing automation. Human visual/audio review is a
   separate required decision.
5. Keep the release stop in force after program verification until explicit release authority is
   granted.
