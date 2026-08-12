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

**Exit:** **PENDING (deepen residual)** — modules on tip under `kinocut/watching/`
(`review`, `metrics`, `mutations`, `vision_qc`, `narrative_qc`) plus MCP/CLI intent
tools. Residual is **GO evidence links + real-media residual**, not “scaffold
missing.” Matrix family: `watching_p3` · blocks claim until PHASE GO or DEFERRED.

## Phase 4 — Multipliers

| Gate | Go | No-go |
| --- | --- | --- |
| Generative last-mile | spend caps + local default | unbounded paid gen |
| OTIO | import/export roundtrip | claim interchange without fixture |
| Review UI | human hot-reload surface | agent-only “review” |
| TTS dub | ES-first, separate from translate | conflate with caption translate |

**Exit:** **PENDING (deepen residual)** — `kinocut/multipliers/*` (5 modules) and TE
multipliers exist on tip. Residual is GO criteria / DEFERRED IDs, not greenfield
rebuild. Matrix family: `multipliers_p4`.

## Track E pillars (Cutfile / Video CI / conversational)

| Gate | Go | No-go |
| --- | --- | --- |
| Cutfile | committable text project renders | JSON dump without schema |
| kinocut-action | CI receipt on push | CI that only runs unit tests |
| Conversational sessions | measured improvement metric | chat without receipts |

**Exit:** **PENDING (mixed residual)** — cutfile today is validate/load
(`kinocut/te/cutfile.py`); render path or DEFERRED ID required for claim.
`kinocut-action` foundations under `.github/actions/kinocut-video-ci/`; conversational
`edit_session` deepen soft. See matrix rows `cutfile`, `kinocut_action`, `conversational`.

## Sound program (not a Phase 1–4 exit; residual portfolio)

| Gate | Go | No-go |
| --- | --- | --- |
| Public S12 join | thin public surface honest | market as full-episode complete |
| S4–S13 packages | residual re-run/deepen green | greenfield rebuild without fail |
| S14 dual-class | live host classes or `external_host_unavailable` residual | pass by skipping a class |
| S15 / product claim | Wave F honesty + L3 claim owner | synthetic S14 alone as product complete |

**Status:** packages present; **product full-episode sound unclaimed**. Authority:
[`2026-08-12-sound-residual-stage-dag.md`](2026-08-12-sound-residual-stage-dag.md),
fixture freeze, residual matrix. July “S5–S15 incomplete” handoffs are **historical** —
do not contradict the residual matrix when staffing.

## Human-only (never agent-close)

- First-10 real users program (#92) — open
- Directory/registry third-party approval (#88) — external reviews still pending (Awesome MCP merged)
- Launch media final cut approval (#90) — open
- Renovate host token (#3) — open
- Do **not** invent completions for the above

## Residual program note (2026-08-12, L1.2)

Phase 3/4/E exits still **PENDING** until GO evidence is linked or a DEFERRED row
with `blocks_portfolio_complete` is minted. Agent work is **deepen/re-verify**, not
missing-module rebuild. Claim bumps to `docs/public_claims.json` are frozen until
**L3** for non–claim-owners (see ROADMAP claim ledger). Ultragoal plan:
`.omc/ultragoal/plans/kinocut-full-build`.
