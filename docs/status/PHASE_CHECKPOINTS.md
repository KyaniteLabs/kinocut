# Phase go / no-go checkpoints (DEC.1)

**Status:** living · **Date:** 2026-08-07  
**Issue:** Forgejo #94

Kill-or-pivot criteria for the trusted-execution plan phases. A phase exits only
when its **go** criteria are evidence-backed; otherwise **no-go** with a residual
ticket or human decision.

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

**Exit:** PENDING — metric floor + review_run skeleton landed; vision/narrative/mutations residual.

## Phase 4 — Multipliers

| Gate | Go | No-go |
| --- | --- | --- |
| Generative last-mile | spend caps + local default | unbounded paid gen |
| OTIO | import/export roundtrip | claim interchange without fixture |
| Review UI | human hot-reload surface | agent-only “review” |
| TTS dub | ES-first, separate from translate | conflate with caption translate |

**Exit:** PENDING.

## Track E pillars (Cutfile / Video CI / conversational)

| Gate | Go | No-go |
| --- | --- | --- |
| Cutfile | committable text project renders | JSON dump without schema |
| kinocut-action | CI receipt on push | CI that only runs unit tests |
| Conversational sessions | measured improvement metric | chat without receipts |

**Exit:** PENDING.

## Human-only (never agent-close)

- First-10 real users program (#92)
- Directory/registry third-party approval (#88)
- Launch media final cut approval (#90)
