# `kinocut_sound` implementation plan index

**Status:** planning and routing only; implementation incomplete; release prohibited

**Design:** [Sonic World audio-play production design](../specs/2026-07-11-kinocut-sound-sonic-world-design.md)

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
