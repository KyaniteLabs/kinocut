# Golden-path timings (WP-F baseline scaffolding)

**Ultragoal:** `kinocut-full-build` · story `G005-l3-release-perf` (partial)  
**Scope:** committed harness + measured baseline rows for cheap path  
**Not in scope:** full L3 claim PR, `docs/public_claims.json` bump, “optimized” product claim

Authority: ROADMAP WP-F · residual matrix `wp_f_baselines` · DEF-wp-f  
Related proof path (untimed / separate): [`docs/GOLDEN_PATH.md`](../GOLDEN_PATH.md) · `scripts/golden_path.py`

## Why this exists

Excellence audit / WP-F required a **documented golden-path p50/p95** before any optimization language. This file is the living receipt for baseline numbers. Empty or partial rows mean “not yet measured on that host,” not green WP-F closeout.

## Documented paths

| Path | Steps | When to use |
| --- | --- | --- |
| **Cheap (default)** | `kino doctor --json` → `kino --format json info <fixture>` | CI-safe / laptop baseline; no FFmpeg encode |
| **Full (optional)** | Cheap steps + `python scripts/golden_path.py` | After residual GO; heavier; writes under `workflows/05-confidence-baseline/output/` |

Default fixture (committed, tiny): `tests/fixtures/golden/workflow_final.mp4`

## How to run

From repo root (Python env with Kinocut importable + FFmpeg for full mode):

```bash
# Cheap baseline (recommended for scaffolding / frequent re-runs)
python3 scripts/golden_path_timings.py --mode cheap --runs 5

# Markdown table only (paste into this file)
python3 scripts/golden_path_timings.py --mode cheap --runs 5 --markdown-only

# JSON payload for tooling
python3 scripts/golden_path_timings.py --mode cheap --runs 5 --json

# Full confidence workflow (slow; optional)
python3 scripts/golden_path_timings.py --mode full --runs 3
```

Paste a new results section below (do not overwrite history; append dated blocks).  
**Do not** bump `docs/public_claims.json` from timing work alone.

## Results template (fill per host)

| step | mode | runs | ok | p50 (s) | p95 (s) | mean (s) | min (s) | max (s) | machine |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| doctor | cheap |  |  |  |  |  |  |  |  |
| info | cheap |  |  |  |  |  |  |  |  |
| golden_path | full |  |  |  |  |  |  |  |  |

Fixture: `tests/fixtures/golden/workflow_final.mp4`  
Recorded: `YYYY-MM-DDTHH:MM:SS+00:00`

## Measured: 2026-08-12 (cheap path)

| Field | Value |
| --- | --- |
| Host class | Darwin / arm64 (Apple Silicon) |
| Python | 3.14.5 |
| Command | `python3 scripts/golden_path_timings.py --mode cheap --runs 5` |
| Full path | measured same day (see block below) |

| step | mode | runs | ok | p50 (s) | p95 (s) | mean (s) | min (s) | max (s) | machine |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| doctor | cheap | 5 | 5 | 1.3643 | 1.4135 | 1.3808 | 1.3559 | 1.4143 | Darwin/arm64 |
| info | cheap | 5 | 5 | 0.4375 | 0.4469 | 0.4400 | 0.4351 | 0.4474 | Darwin/arm64 |

Fixture: `tests/fixtures/golden/workflow_final.mp4`  
Recorded: `2026-08-12T14:59:34.357224+00:00`

## Measured: 2026-08-12 (full path, n=3)

| Field | Value |
| --- | --- |
| Host class | Darwin / arm64 (Apple Silicon) |
| Python | 3.14.x |
| Command | `python3 scripts/golden_path_timings.py --mode full --runs 3` |

| step | mode | runs | ok | p50 (s) | p95 (s) | mean (s) | min (s) | max (s) | machine |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| doctor | full | 3 | 3 | 1.4396 | 1.82 | 1.5601 | 1.3784 | 1.8623 | Darwin/arm64 |
| info | full | 3 | 3 | 0.4489 | 0.4882 | 0.458 | 0.4326 | 0.4926 | Darwin/arm64 |
| golden_path | full | 3 | 3 | 9.4835 | 9.703 | 9.5571 | 9.4605 | 9.7274 | Darwin/arm64 |

Fixture: `tests/fixtures/golden/workflow_final.mp4`  
Recorded: `2026-08-12T15:16:30.129698+00:00`

**Honesty:** These are cold **CLI process** wall times (new interpreter per sample), not in-process engine loops. They establish a **baseline**, not an “optimized” product claim. No `public_claims.json` bump from timings alone.

## Acceptance (scaffolding vs L3)

| Gate | Status |
| --- | --- |
| Script under `scripts/` | `scripts/golden_path_timings.py` |
| Status template with p50/p95 columns | this file |
| Cheap path measured once | when Measured block has numbers |
| Full path measured | optional; not required for scaffolding |
| public_claims bump | **forbidden** until L3 claim owner PR |
| WP-F / DEF-wp-f close | only after durable p50/p95 + residual GO matrix |

## Notes

- Full golden path remains the **functional** proof (`scripts/golden_path.py`); this harness is the **timing** companion.
- p50/p95 use linear interpolation over sorted wall-clock samples from `time.perf_counter()`.
- Cold vs warm process starts: each sample spawns a new `python -m kinocut` process (includes interpreter + import cost). That matches agent/CLI first-call cost better than in-process loops.
