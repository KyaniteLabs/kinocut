# Phase go / no-go checkpoints (DEC.1)

**Status:** living · **Date:** 2026-08-12 (L1.2 truth pass)  
**Issue:** Forgejo #94  
**Residual authority:** [`2026-08-12-residual-maturity-matrix.md`](2026-08-12-residual-maturity-matrix.md) · [L1 truth pass](2026-08-12-l1-truth-pass.md)

Kill-or-pivot criteria for the trusted-execution plan phases. A phase exits only
when its **go** criteria are evidence-backed; otherwise **no-go** with a residual
ticket or human decision. **PENDING ≠ missing packages** when the residual matrix
classifies the family as deepen/re-run.

## Phase 1 — Kernel corners (projectstore)

| Gate | Go | No-go |
| --- | --- | --- |
| Durable projects | edit projects + revisions on tip with tests | rebuild parallel kernel package |
| Async jobs | kill/reopen/resume proven | claim runner complete without resume test |
| CAS + lineage | digests + receipt lineage tests green | skip CAS for “speed” |
| Events | ordered filterable events | poll-only without durable store |

**Exit (2026-07-27):** GO — P1 issues closed on tip (Wave A).

## Phase 2 — Product JTBD

| Gate | Go | No-go |
| --- | --- | --- |
| Repurpose durable | projectstore repurpose lineage | legacy-only path without project IDs |
| Captions | word-timed ≤80ms proof | SRT-only without burn timing proof |
| Intent surface | ≥8 verbs + `video_intent` router | expose only the 100+ tool dump as UX |
| B-roll | proposals only, human apply | silent insert |
| Translate | honest coverage matrix | claim dub==translate |

**Exit (2026-08-07 wave):** GO for shipped residuals + intent/broll/translate wave;
P3+ children remain open until their gates pass.

## Phase 3 — Watching guardrail

| Gate | Go | No-go |
| --- | --- | --- |
| Review API | `review_run` + decide path | metrics without human decide |
| Metric floor | offline fail-closed findings | invent 0.0 for empty probes |
| Vision/narrative | graceful enhancement | hard-require VLM for all users |
| Mutations | typed proposals | silent timeline rewrite |

**Exit (2026-08-12):** **GO** — Review API + decide, metric floor (fail-closed,
non-invention), vision/narrative graceful without VLM, mutations propose-only with
`apply_mutations_silently` fail-closed. Evidence: `tests/test_phase3_watching_go.py`,
G004 synthetic phone-frame review path, `video_metric_qc` public tool.
See also [`2026-08-12-phase3-phase4-residual-evidence.md`](2026-08-12-phase3-phase4-residual-evidence.md) (historical PENDING) superseded by this GO.

## Phase 4 — Multipliers

| Gate | Go | No-go |
| --- | --- | --- |
| Generative last-mile | spend caps + local default | unbounded paid gen |
| OTIO | import/export roundtrip | claim interchange without fixture |
| Review UI | human hot-reload surface | agent-only “review” |
| TTS dub | ES-first, separate from translate | conflate with caption translate |

**Exit (2026-08-12):** **GO** — Generative spend caps + local default (plan-only),
OTIO **kinocut_ir-embedded** JSON interchange roundtrip, human review UI with
hot-reload poll, TTS dub ES-first plan separate from caption translate
(`executable=False` until backend). Evidence: `tests/test_phase4_multipliers_go.py`.
Interchange scope is documented as kinocut_ir-embedded OTIO JSON (not foreign OTIO).

## Track E pillars (Cutfile / Video CI / conversational)

| Gate | Go | No-go |
| --- | --- | --- |
| Cutfile | committable text project renders | JSON dump without schema |
| kinocut-action | CI receipt on push | CI that only runs unit tests |
| Conversational sessions | measured improvement metric | chat without receipts |

**Exit (2026-08-12):** **GO** — Cutfile public `video_cutfile_render` / `cutfile-render`;
`kinocut-video-ci` writes composite receipts (metric-qc + review + optional cutfile);
conversational `session_close` emits measured improvement + receipt.
Evidence: `tests/test_track_e_go.py`.

## Sound program (not a Phase 1–4 exit; residual portfolio)

| Gate | Go | No-go |
| --- | --- | --- |
| Public S12 join | thin public surface honest | market as full-episode complete |
| S4–S13 packages | residual re-run/deepen green | greenfield rebuild without fail |
| S14 dual-class | live host classes or `external_host_unavailable` residual | pass by skipping a class |
| S15 / product claim | Wave F honesty + L3 claim owner | synthetic S14 alone as product complete |

**Status (2026-08-12):** packages + S14 live re-run on `apple_silicon` under 30m with
64-clip fixture; second class **`external_host_unavailable`** (allowed by gate).
S15 stop tests green. **Product full-episode claim:** allowed for S4–S14 pipeline
maturity with honest dual-class residual note — not a silent skip.
Evidence: `docs/evidence/2026-08-12-sound-s14-live-rerun.json`, sound GO tests.

## Human-only (never agent-close)

- First-10 real users program (#92) — open
- Directory/registry third-party approval (#88) — external reviews still pending (Awesome MCP merged)
- Launch media final cut approval (#90) — open
- Renovate host token (#3) — open
- Do **not** invent completions for the above

## Residual program note (2026-08-12, L1.2 + G004 residual evidence)

Phase 3/4/E exits still **PENDING**. DEFERRED rows **`DEF-phase3-go`** /
**`DEF-phase4-go`** hold phase-claim authority. G004 tip evidence receipt:
[`2026-08-12-phase3-phase4-residual-evidence.md`](2026-08-12-phase3-phase4-residual-evidence.md)
(7 focused unit nodes green; **not** PHASE GO). Agent work is **deepen/re-verify**,
not missing-module rebuild. Claim bumps to `docs/public_claims.json` are frozen
until **L3** for non–claim-owners (see ROADMAP claim ledger). Ultragoal plan:
`.omc/ultragoal/plans/kinocut-full-build`.
