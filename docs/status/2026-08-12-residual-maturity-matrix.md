# Residual Maturity Matrix (L0.4)

**Date:** 2026-08-12  
**Tip branch:** `ultragoal/kinocut-full-build`  
**Ultragoal:** `.omc/ultragoal/plans/kinocut-full-build` G001  
**Evidence basis:** code + tests + evidence paths (not July prose alone)

| family | class | evidence_paths | residual_tickets | blocks_claim? |
|--------|-------|----------------|------------------|---------------|
| ssrf_c1 | verify-only | `kinocut/ai_engine/download.py` pin/peer; `tests/test_ai_features.py` SSRF; 60-pass SSRF/preview filter suite | HUMAN_GATES C1 closed L1.2 (2026-08-12) | N (security already on tip) |
| preview_m1 | verify-only | `kinocut/hyperframes_engine.py` `_active_previews`/`stop_preview`/`atexit`; `tests/test_hyperframes_engine.py` stop_preview | HUMAN_GATES M1 closed L1.2 (2026-08-12) | N |
| hyperframes_ops_policy | verify-only (fixed) | Split `hyperframes_ops_helpers.py`; ops ~680 LOC; guardrail locks ops+helpers | Keep ≤800 | N |
| watching_p3 | deepen | `kinocut/watching/{review,metrics,mutations,vision_qc,narrative_qc}.py`; MCP/CLI intent tools; [phase3/4 residual evidence](2026-08-12-phase3-phase4-residual-evidence.md) | `DEF-phase3-go` (real-media GO) | Y until PHASE GO |
| multipliers_p4 | deepen | `kinocut/multipliers/*` (5 modules); [phase3/4 residual evidence](2026-08-12-phase3-phase4-residual-evidence.md) | `DEF-phase4-go` | Y until PHASE GO |
| sound_S4 | re-run | foundation packages present | Re-verify contracts | N if green |
| sound_S5 | re-run/deepen | `kinocut_sound/voice/` | Residual-only tickets if tests fail | Y for full-episode claim |
| sound_S6 | re-run/deepen | `voice/clone.py`, `blend.py` | same | Y full-episode |
| sound_S7 | re-run/deepen | `kinocut_sound/post/` | same | Y full-episode |
| sound_S8 | re-run/deepen | `kinocut_sound/world/` | same | Y full-episode |
| sound_S9 | re-run/deepen | `kinocut_sound/mix/` | same | Y full-episode |
| sound_S10 | re-run/deepen | `kinocut_sound/voice_consistency/` | same | Y full-episode |
| sound_S11 | re-run/deepen | `kinocut_sound/qa/` | same | Y full-episode |
| sound_S12 | re-run/deepen | `kinocut_sound/public/`, `kinocut/sound_joins/` | ROADMAP thin-S12 honesty synced 2026-08-12 (L1.2) | Y full-episode |
| sound_S13 | re-run | `sound_joins` + host joins | dual-class residual | Y full-episode |
| sound_S14 | re-run | `docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json` (64 clips, dual-class, under_30m) | Re-run live host classes | **Synthetic ≠ product complete** |
| sound_S15 | deepen | acceptance residual | Product honesty + human adversarial review | Y product claim |
| cutfile | deepen (thin render) | `kinocut/te/cutfile.py` + `kinocut/te/cutfile_render.py` (compile→workflow OP_ADAPTERS→`render_workflow`); tests in `tests/test_te_and_mutations.py` | Optional MCP/CLI surface (not claimed; keep public_claims stable) | N for library render claim; Y if MCP/CLI claimed without surface bump |
| kinocut_action | deepen | `.github/actions/kinocut-video-ci/` | CI receipt on push | soft |
| conversational | deepen | `kinocut/te/edit_session.py` | measured metric + receipt depth | soft |
| durable_repurpose | deepen | `kinocut/projectstore/` (18 files) | honesty vs seed skill | soft |
| g004 | human-only | HUMAN_GATES / fixtures | human media | Y shorts honesty |
| mcpb | human-only + agent pack | foundations | human sign | Y production pack |
| dual_host_face | deepen | dual-host docs | verify after claim PRs | Y public face |
| wp_f_baselines | deepen | `scripts/golden_path_timings.py` + cheap p50/p95 in `docs/status/golden-path-timings.md` (2026-08-12); full path optional | full-path samples + residual GO before optimize claim | N until “optimized” claim |
| human_gates | human-only | `docs/HUMAN_GATES.md` | #3 #88 #90 #92 | Y agent-complete |
| sphere_360 | shipped on tip | `kinocut/te/sphere_*.py`; `docs/360_ASSEMBLY.md`; `tests/test_sphere_assembly.py` | Optional real-X4 dogfood | N published 1.13.4; Y if claimed on PyPI without a release cut |

**Rule:** No L2 ticket re-implements `verify-only` without a failing case.

## Supersession (2026-08-12 evening)

Product pipeline closed in **1.13.4** — Phase 3/4/Track E **GO**. See [`2026-08-12-product-pipeline-complete.md`](2026-08-12-product-pipeline-complete.md) and updated `DEFERRED.md`.
