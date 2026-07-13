# `kinocut_sound` implementation plan index

**Status:** S1-S4 implemented; S5-S15 incomplete; release prohibited

**Design:** [Sonic World audio-play production design](../specs/2026-07-11-kinocut-sound-sonic-world-design.md)

## Current implementation state

- **S1 complete:** backend-neutral foundation contracts.
- **S2 complete:** fail-closed authorization, provenance, privacy, leases, revocation, lineage,
  blend/cloud scope, and quarantine/deletion runtime.
- **S3 complete:** sealed registry, versioned presets/config, local/cloud provider policy, complete
  render fingerprints, and authorization-aware cache with real S2 lineage.
- **S4 complete:** strict generic/WF parser plus deterministic pure episode planning against typed
  fakes, including pacing, designed silence, routing intent, and Foley cue contracts.
- **S5-S15 open:** proceed only when their named dependencies in the design are green.

Exact implementation, review, test, and release-stop evidence is recorded in the
[S2/S4 checkpoint](../../status/2026-07-13-sound-s2-s4-integration-checkpoint.md) and the
[S3 checkpoint](../../status/2026-07-13-sound-s3-integration-checkpoint.md).

The 15 bounded S1-S15 leaves in the design are the authoritative dependency graph. The older
ten-module summary below remains a product-area overview, not implementation status.

## Module sequence

1. Foundation: SoundPlan, timeline, routing, delivery, consent, receipt, capability, and render
   fingerprint contracts.
2. Voice providers and profiles.
3. Restoration, post-processing, and spatial chain.
4. Script parser and episode assembly.
5. Ambience, Foley, and world-building.
6. Voice consistency and roster management.
7. QA, metadata, loudness, true-peak, and provenance.
8. Orchestration, cancellation/resume, caching, and deterministic stage reuse.
9. Scalability and the representative full-episode benchmark.
10. Standalone Python/CLI surfaces followed by serialized Kinocut/MCP adapters.

## Parallel lanes

After foundation contracts stabilize, voice, assembly, and selected QA fixture work may proceed in
parallel. Post/spatial, ambience, voice-management, QA, and adapter-core work may then occupy up to
four disjoint author lanes. Orchestration joins those modules; benchmarking follows orchestration;
the public Kinocut adapter is a serialized controller-owned join.

Current critical path:

```text
(S5 base voice || S7 post/spatial || S8 ambience)
S5 -> (S6 cloning/blending || S10 voice consistency)
(S5 + S7 + S8) -> S9 assembly/mix/stems
(S4 + S7 + S9) -> S11 QA/metadata
(implemented S4-S11) -> S12 public parity -> S13 host joins -> S14 benchmark -> S15 acceptance
```

S5, S7, and S8 are now parallel-ready because S1-S4 are complete.

See [the full parallel execution plan](../../plans/2026-07-12-wishlist-parallel-execution.md) for
ownership, branch, integration, verification, and release-stop rules.

## Acceptance gate

The sound program is incomplete until the representative 50–80-clip fixture passes cold and warm
on each currently approved benchmark class, with runtime host identity and hardware/software
fingerprints captured rather than hardcoded. A missing required benchmark environment is
`external_host_unavailable`, never a pass. Human authorization wait is excluded from engineering
duration estimates.

After sound verification, the controller runs whole-program verification and stops before any
release action.
