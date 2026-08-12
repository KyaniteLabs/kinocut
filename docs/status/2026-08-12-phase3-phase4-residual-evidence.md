# Phase 3 / Phase 4 residual evidence (G004)

**Date:** 2026-08-12  
**Branch tip:** `ultragoal/kinocut-full-build` @ `7618e76`  
**Ultragoal story:** G004 residual — produce GO evidence from tip code + tests  
**Authority:** [`PHASE_CHECKPOINTS.md`](PHASE_CHECKPOINTS.md) · [`DEFERRED.md`](DEFERRED.md) · [`2026-08-12-residual-maturity-matrix.md`](2026-08-12-residual-maturity-matrix.md)  
**Claim freeze:** does **not** bump `docs/public_claims.json`

## Verdict

| Phase | Exit | Residual IDs |
| --- | --- | --- |
| **Phase 3 — Watching guardrail** | **PENDING** | `DEF-phase3-go` (`watching_p3`) |
| **Phase 4 — Multipliers** | **PENDING** | `DEF-phase4-go` (`multipliers_p4`) |

**Do not claim PHASE GO.** Packages and gate *shapes* are on tip with green unit coverage, but formal exit criteria still require linked real-media / formal GO evidence called out by DEFERRED reopen conditions. Evidence below is intentionally bounded; weak spots are listed rather than papered over.

Historical session lore (“watching 28 passed / multipliers 42 passed”) is **not** reproducible as focused P3/P4 suites on this tip. Live focused suite = **7 passed** (see Tests). The “42” figure in other status docs is the excellence-audit fleet check, not multipliers unit count.

---

## What is on tip

### Phase 3 — `kinocut/watching/` (6 modules, ~540 LOC)

| Module | Role vs gate | On-tip behavior |
| --- | --- | --- |
| `review.py` | Review API | `run_review` + `decide_review`; accept-of-fail requires non-empty reason |
| `metrics.py` | Metric floor | Offline duration / blackdetect / loudnorm proxy; missing probes → `severity=warn` + `evidence.available=False` (does **not** invent LUFS `0.0`) |
| `mutations.py` | Typed proposals | `propose_mutations_from_findings` → `apply_policy="human_review_required"` only |
| `vision_qc.py` | Vision graceful | Never hard-requires VLM; structural sample + availability note |
| `narrative_qc.py` | Narrative heuristics | First-15s / end-card window offline checks |
| `__init__.py` | Public package surface | Re-exports above |

**MCP / CLI wiring (present):**  
`video_review_run`, `video_review_decide`, `video_propose_mutations`, vision/narrative QC tools in `server_tools_intent.py`; CLI `review-run`, `review-decide`, `qc-vision`, `qc-narrative`, `propose-mutations` in `cli/handlers_intent.py`. Public surface registry lists these names (`tests/test_public_surface.py`).

### Phase 4 — `kinocut/multipliers/` (5 modules, ~272 LOC)

| Module | Role vs gate | On-tip behavior |
| --- | --- | --- |
| `generative.py` | Spend caps + local default | `plan_generative_last_mile` — **plan only**; local allowed; paid denied when estimate > cap (default cap `0.0`) |
| `otio_io.py` | OTIO import/export | Simplified OTIO **JSON** bridge over Timeline IR; full-fidelity import requires embedded `metadata.kinocut_ir` |
| `review_ui.py` | Human hot-reload surface | Static `review.html` with 2s poll — not agent-only review |
| `tts_dub.py` | ES-first dub plan | `plan_tts_dub` → `executable=False`; ES brand-primary; separate from caption translate |
| `__init__.py` | Package surface | Re-exports above |

**MCP / CLI wiring (present):**  
`video_generative_plan`, `video_otio_export`, `video_otio_import`, `video_review_ui`, dub plan tool; CLI `otio-export`, `otio-import`, `review-ui`.

---

## Gate matrix (evidence vs residual)

### Phase 3 gates

| Gate | Code evidence | Test evidence | Residual / gap |
| --- | --- | --- | --- |
| Review API (`review_run` + decide) | `run_review` / `decide_review` | `test_review_run_and_decide` on golden fixture | No multi-minute / phone-frame real-media corpus (`DEF-g004-media` related honesty) |
| Metric floor fail-closed | `run_metric_qc`; missing probe → skip/warn | Exercised **indirectly** via `run_review`; **no dedicated `run_metric_qc` test** | Dedicated metric-floor cases + non-golden media still open |
| Vision/narrative graceful | `require_vlm` never hard-fails product path | `test_vision_and_narrative_on_golden` | Vision is structural-only; no real VLM rubric score path claimed |
| Mutations typed proposals | `human_review_required` only | `test_propose_mutations_from_findings` (synthetic findings) | No apply-path silence proof against a live timeline rewrite end-to-end |

### Phase 4 gates

| Gate | Code evidence | Test evidence | Residual / gap |
| --- | --- | --- | --- |
| Generative spend caps + local default | Cap compare; local always allowed | `test_generative_spend_cap` | Plan-only (honest); no live provider integration proof required for plan gate, but formal PHASE GO still open |
| OTIO import/export roundtrip | export embeds IR; import restores IR | `test_otio_export_import` | **Not** full OpenTimelineIO library interchange; foreign OTIO without `kinocut_ir` fails closed |
| Review UI human surface | HTML + hot-reload poll | `test_review_ui` writes file | Smoke only — no browser/human-session receipt |
| TTS dub ES-first ≠ translate | Plan + coverage report; `executable=False` | `test_tts_dub_plan_not_executable` | Backend not bundled; execution deferred by design |

---

## What tests cover (live, this pass)

**Command (focused P3/P4 nodes):**

```bash
python3 -m pytest \
  tests/test_intent_surface.py::test_review_run_and_decide \
  tests/test_te_and_mutations.py::test_propose_mutations_from_findings \
  tests/test_finish_campaign.py::test_otio_export_import \
  tests/test_finish_campaign.py::test_generative_spend_cap \
  tests/test_finish_campaign.py::test_review_ui \
  tests/test_finish_campaign.py::test_tts_dub_plan_not_executable \
  tests/test_finish_campaign.py::test_vision_and_narrative_on_golden \
  -v --tb=short
```

**Result (2026-08-12, tip `7618e76`):** **7 passed** in ~0.22s.

| Node | Family |
| --- | --- |
| `tests/test_intent_surface.py::test_review_run_and_decide` | watching |
| `tests/test_te_and_mutations.py::test_propose_mutations_from_findings` | watching |
| `tests/test_finish_campaign.py::test_vision_and_narrative_on_golden` | watching |
| `tests/test_finish_campaign.py::test_otio_export_import` | multipliers |
| `tests/test_finish_campaign.py::test_generative_spend_cap` | multipliers |
| `tests/test_finish_campaign.py::test_review_ui` | multipliers |
| `tests/test_finish_campaign.py::test_tts_dub_plan_not_executable` | multipliers |

**Adjacent (not counted as P3/P4 unit GO):**  
`tests/test_finish_campaign.py` + `tests/test_intent_surface.py` + `tests/test_te_and_mutations.py` together → **26 passed** (includes TE/intent non-P3/P4 cases). Public-surface name registration covers tool symbols but is not behavioral GO.

**Ad-hoc metric probe (golden `workflow_final.mp4`, 1.0s):**

| check_id | severity | notes |
| --- | --- | --- |
| `duration.min` | info | measured duration |
| `black_frames.ratio` | info | measured ratio `0.0` (real blackdetect) |
| `audio.lufs` | warn | `available: False` — not fabricated |
| `av_sync.proxy` | info | explicitly unclaimed |

---

## Why exit remains PENDING (not GO)

1. **DEFERRED reopen is explicit:** `DEF-phase3-go` requires *linked real-media GO evidence*; golden 1s fixture + unit smoke is not that bar.  
2. **Metric floor lacks a first-class test module** and real-media fail cases (forced short / forced black).  
3. **OTIO is a Kinocut-IR JSON bridge**, not proven third-party OTIO interchange — claiming Phase 4 GO would over-read the gate wording “import/export roundtrip.”  
4. **Review UI / generative / TTS** are plan-or-smoke surfaces; acceptable as shipped *capabilities*, insufficient alone for portfolio PHASE exit without formal GO link.  
5. **No public claim bump** is authorized until L3 claim owner; this doc freezes honesty at residual deepen class.

## Residual list (must match DEFERRED)

| id | family | blocks_portfolio_complete | reopen_condition (from DEFERRED) |
| --- | --- | --- | --- |
| `DEF-phase3-go` | `watching_p3` | Y phase claim | Linked real-media GO evidence |
| `DEF-phase4-go` | `multipliers_p4` | Y phase claim | Linked GO evidence |

Related non-phase rows that still bound honesty (not flipped by this pass):

- `DEF-g004-media` — multi-minute / phone-frame fixtures  
- Human gates `#88` / `#90` / `#92` / `#3` — never agent-closed  

## What would flip to GO (future; not claimed now)

**Phase 3 GO** when all are true and linked from `PHASE_CHECKPOINTS.md`:

1. Real-media review_run + decide path on non-golden multi-shot source (or explicit product waiver + DEFERRED supersession).  
2. Dedicated metric-floor tests: fail duration, fail/warn black, unavailable-probe non-invention.  
3. Mutations still propose-only under a documented apply surface (no silent rewrite).  
4. Vision/narrative remain graceful; no hard VLM product requirement.

**Phase 4 GO** when all are true and linked:

1. OTIO fixture roundtrip documented as **supported interchange scope** (kinocut_ir-embedded) **or** real OTIO library path with foreign fixture.  
2. Generative plan caps tested + local default; paid path remains non-auto.  
3. Review UI smoke retained; optional human session note.  
4. TTS dub remains ES-first and separate from translate; executable honesty unchanged until backend lands.

---

## Doc actions from this pass

| File | Action |
| --- | --- |
| This evidence doc | Created |
| `PHASE_CHECKPOINTS.md` | Exit stays **PENDING**; residual IDs + link to this doc |
| `DEFERRED.md` | Keep `DEF-phase3-go` / `DEF-phase4-go`; reason may cite this doc |
| `docs/public_claims.json` | **Not touched** |
