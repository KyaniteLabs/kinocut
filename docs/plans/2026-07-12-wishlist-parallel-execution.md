# Wishlist and Sonic World parallel execution plan

**Status:** approved implementation routing; incomplete; stop before release

**Baseline:** finish and independently review Wave 3 before branching downstream work

## Executive summary

Use at most four feature authors plus one controller/reviewer. The safe acceleration comes from
parallelizing disjoint deep modules while serializing public-surface joins and the full FFmpeg test
gate. More workers than that increase merge risk in shared contracts, defaults, CLI routing, and
public documentation.

## Dependency and execution waves

| Wave | Parallel author lanes | Join or gate |
| ---: | --- | --- |
| -1 | Close remaining Wave 3 review findings | Independent review; full repository gate; immutable checkpoint |
| 0 | Audio continuity core; subtitle/graphics QA core; approved clip registry core | Controller serializes public API/docs joins; bed registry waits on audio-bed contract |
| 1 | `kinocut_sound` foundation and contracts | Starts after audio continuity contracts stabilize; finish registry bed lane |
| 2 | Sound voice providers; sound script/assembly; editorial planning | One controller integration at a time |
| 3 | Sound post/spatial chain; review package and decisions | Full-gate semaphore after each accepted unit |
| 4 | Sound ambience; sound QA/metadata; sound adapter boundary; CLI/agent ergonomics | Cap at four authors; controller owns shared surfaces |
| 5 | Sound voice management; sound orchestration; sound scalability; learning reports | Benchmark fixtures can start only after their contracts stabilize |
| 6 | Sound episode DAG renderer | Integrated sound modules required |
| 7 | Sound benchmark, then Kinocut adapter | Serialized public/integration joins |
| 8 | Full-episode acceptance; gated kernel only if its external contract and human gate are green | Kernel substitutes are forbidden |
| 9 | Sound final verification, then whole-program verification | Stop and request release authority |

## Critical path

```text
Wave 3 review and proof
  -> audio continuity
  -> sound foundation
  -> voice + assembly
  -> post + ambience + QA + adapters
  -> orchestration + scalability
  -> episode renderer
  -> benchmark
  -> Kinocut integration
  -> full-episode acceptance
  -> sound verification
  -> whole-program verification
```

The protected-timeline kernel is a separate hard-gated branch. It cannot begin merely because
other lanes are ready. It requires the durable kernel contract named in the kernel plan and an
explicit human decision to remove the gate.

## Ownership boundaries

Feature authors own focused engines, contracts, and focused tests for one lane. The controller
alone owns cross-lane state and joins:

- MCP registration and public tool registries;
- central CLI parser/dispatch and non-TTY output policy;
- Python client aggregate surfaces;
- shared defaults, validation sets, and resource limits;
- package exports and capability registries;
- public API documentation, agent skill, and public-surface count tests;
- program ledger, checkpoint receipt, and final release-stop record.

Within sound, each author owns one module boundary: foundation, voice, post/spatial, assembly,
ambience, voice management, QA/metadata, orchestration, scalability, or adapters. No author edits
another lane's module during the same wave.

## Branch and integration protocol

1. Branch each bounded unit from the last independently reviewed integration tip.
2. Write the failing contract/regression test first; capture RED, then focused GREEN.
3. Keep one change unit per commit. Do not mix public-surface joins into feature commits.
4. Controller rebases and reviews one unit at a time, then runs focused tests.
5. Acquire the single full-suite semaphore before running repository-wide FFmpeg tests.
6. Run imports, Ruff, diff hygiene, leak checks, size gates, public-surface parity, and the full
   suite on the exact integrated source.
7. Record the immutable checkpoint before downstream branches use the new tip.
8. Remove merged temporary branches and worktrees; retain only active review branches.

## Release boundary

Implementation and draft review are authorized. Version bumps, tags, package uploads, directory
submissions, deployment, release creation, and announcements remain prohibited. After final
program verification, stop with the coverage matrix, test/leak receipts, known limitations,
optional capability state, and human-review checklist.
