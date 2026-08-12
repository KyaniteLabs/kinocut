# Sound residual stage DAG (L0.5)

**Date:** 2026-08-12  
**Fixture freeze:** see `docs/status/2026-08-12-sound-fixture-freeze.md` (L0.5b)

## Live inventory

- Package tree: `kinocut_sound/` (93 Python files) including `voice/`, `voice_consistency/`, `post/`, `world/`, `mix/`, `qa/`, `public/`, episode assembly, authorization.
- Host joins: `kinocut/sound_joins/` (5 modules).
- Historical S14: `docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json` — fixture `sound-bench-v1`, **64 clips**, both classes cold/warm `under_30m: true` (synthetic times).

## Design waves (execution order)

```text
Wave A: S5 || S7 || S8     (leaves ≤3 if residual deepen/greenfield)
Wave B: S5 → (S6 || S10)   (leaves ≤2)
Wave C: S4+S5+S7+S8 → S9   (serial join)
Wave D: S4+S7+S9 → S11
Wave E: → S12 → S13
Wave F: → S14 → S15
```

## Residual-only staffing

| Stage | Initial class | L2 action |
|-------|---------------|-----------|
| S4–S13 packages | re-run / deepen | Run stage tests; open deepen tickets only on fail or missing GO evidence |
| S14 | re-run | Re-run dual-class bench; missing class → `external_host_unavailable` residual (never silent skip) |
| S15 | deepen | Acceptance + product claim honesty; independent sound review remains human residual |

**Forbidden:** greenfield rebuild of stages classified verify-only/re-run without failing case.

## Product claim policy

- Synthetic S14 re-pass ≠ “full-episode sonic world complete.”
- Product claim only via L3 claim owner after residual Wave F honesty.
