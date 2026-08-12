# Deferred IDs (product pipeline after 1.13.4)

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
| DEF-mcpb-sign | mcpb | **N/A / closed** — no signing key in this org; **unsigned** pack + checklist is the supported product path |
| DEF-splus-95 | wp_a | **CLOSED** — dual-host S+ 100 on tip |
| DEF-wp-f | wp_f | **CLOSED** as baseline (not optimize claim) |

## Still open (non-product growth/ops or human crypto)

| id | family | reason | owner | blocks_portfolio_complete | reopen_condition | date |
|----|--------|--------|-------|---------------------------|------------------|------|
| DEF-human-88 | directories | Third-party review pending | Human | N product timeline | Operator evidence | 2026-08-12 |
| DEF-human-90 | launch | Posts not published | Human | N product timeline | Approve & publish | 2026-08-12 |
| DEF-human-92 | first-10 | Real users program | Human | N product timeline | 10 first-runs | 2026-08-12 |
| DEF-human-3 | renovate | Host token | Human/ops | N product | Token enabled | 2026-08-12 |
| DEF-ci-light | ci_topology | light runner | Ops | N product | light label available | 2026-08-12 |
Product pipeline (Phase 1–4 + Track E + sound S14/S15 maturity + G004 synthetic + MCPB **unsigned** pack) is **complete**. Growth/human ops rows do not block product timeline GO.

**MCPB signing:** Not a product gap. There is no code-signing key for multi-platform MCPB. Ship/install via PyPI/`pip install kinocut`, npm, or **unsigned** MCPB pack. Reopen only if a real signing key is acquired later.
