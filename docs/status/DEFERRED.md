# Deferred IDs (product pipeline after 1.14.0)

**Schema:** `id | family | reason | owner | blocks_portfolio_complete | reopen_condition | date`

## Closed product residuals (2026-08-12)

| id | family | resolution |
|----|--------|------------|
| DEF-phase3-go | watching_p3 | **CLOSED** — PHASE 3 Exit GO; `tests/test_phase3_watching_go.py` |
| DEF-phase4-go | multipliers_p4 | **CLOSED** — PHASE 4 Exit GO; `tests/test_phase4_multipliers_go.py` |
| DEF-cutfile-mcp | cutfile | **CLOSED** — `video_cutfile_render` + `cutfile-render` public surface |
| DEF-s14-live | sound_S14 | **CLOSED** — live apple_silicon 64-clip under_30m; second class `external_host_unavailable` |
| DEF-sound-product | sound_S15 | **CLOSED (honest)** — packages + S15 tests + S14 live; dual-class second host residual noted |
| DEF-g004-media | g004 | **CLOSED (synthetic)** — `scripts/make_g004_fixtures.py` phone-frame multi-shot pack + review path |
| DEF-mcpb-sign | mcpb | **N/A / closed** — no signing key in this org; unsigned is the supported staged path, while exact-digest runtime and install gates remain separate |
| DEF-splus-95 | wp_a | **CLOSED** — dual-host S+ 100 on tip |
| DEF-wp-f | wp_f | **CLOSED** as baseline (not optimize claim) |

## Still open (non-product growth/ops or human crypto)

| id | family | reason | owner | blocks_portfolio_complete | reopen_condition | date |
|----|--------|--------|-------|---------------------------|------------------|------|
| DEF-human-88 | directories | Third-party review pending | Human | N product timeline | Operator evidence | 2026-08-12 |
| DEF-human-90 | launch | Posts not published | Human | N product timeline | Approve & publish | 2026-08-12 |
| DEF-human-92 | first-10 | **CLOSED (2026-08-12)** — obsolete; live adoption: 107 GitHub stars, 25 forks, ~23k PyPI downloads last month | — | N | Do not re-open as “first 10 missing” | 2026-08-12 |
| DEF-human-3 | renovate | Host token | Human/ops | N product | Token enabled | 2026-08-12 |
| DEF-ci-light | ci_topology | light runner | Ops | N product | light label available | 2026-08-12 |
The prior MCPB checklist was planning evidence, not an executed clean-machine or desktop-install gate. Other product tracks retain their recorded status; staged MCPB readiness remains evidence-bound.

**MCPB signing:** Not a product gap. There is no code-signing key for multi-platform MCPB. The staged artifact remains unsigned and labeled `user-configured-local-access`; signing status does not substitute for validator, hosted-runtime, desktop-install, or publication evidence.
