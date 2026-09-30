# Kinocut: quality, reliability, latency, cost and intentional intelligence

September 30, 2026. Team review of the current checkout, including its pre-existing uncommitted optimizations. This review made no new repository changes. Local reproductions and small-fixture measurements are distinguished from source inspection, publisher claims and proposed experiments.

## The direction

Build an evidence-driven editor: decode and infer once, keep immutable source-linked observations, rank finite proposals, spend general-purpose reasoning on ambiguous editorial choices, and have code verify execution and publication. The priority is cost per successful reviewed deliverable, not increasing any source category percentage.

**JEV correction:** JEV is not JEPA. Current GitHub search identifies Jev as TypeSafe’s System One typed-decision model. The earlier JEPA substitution was incorrect. Official TypeSafe skill and SDK sources now confirm typed Choice, Noul (P[yes]) and Score interfaces over supplied state. See JEV-RESEARCH.md. Do not transfer JEPA’s architecture or claimed abilities to Jev.

## What was actually reproduced

| Finding | Evidence | Consequence / next repair |
|---|---|---|
| Invented voice similarity | SHA hashes mapped to arbitrary 0.45–0.75 “similarity”; every different stream falls below drift threshold0.85 | Expose exact encoded-stream preservation honestly; semantic identity/style requires a real, calibrated acoustic analyzer |
| CAS cannot recover GC’d content | Ingest→GC→re-ingest returns success; resolution rejects historical deletion | One authoritative availability lifecycle; recorded verified restoration or explicit rejection |
| 10-bit QC is wrong | Same gray FFV1: 8-bit YAVG126/pass, 10-bit YAVG505/blown highlights | Normalize signal units with bit depth/range; separate HDR delivery policies |
| Entire black clip passes | 0.52s,25fps all-black video reports ratio0.923 and pass | Close terminal frame intervals, measure decoded coverage and handle VFR |
| Stale cached QC | Replace black with white at same path: reused checker still16; fresh checker235 | Cache by verified source snapshot and analysis configuration, not pathname |
| Missing visual evidence passes | Requested frames beyond EOF yield zero; required VLM unavailable; verdict pass | Separate prepared/assessed/skipped/inconclusive/pass/fail; coverage is explicit |
| Failure overwrites output | Conversion callback raises; an existing destination’s bytes nevertheless change | Stage→verify→publish, clean failed work, preserve prior output |
| Demo translation corrupts text | “unlikely”→“unme gustaly”; “Worldwide”→“mundowide” | Mark demo unavailable for production translation; real MT plus cue/entity checks |

These are separate from intentional scoring policies. Existing aggregate quality thresholds are tested behavior; introduce explicit mandatory delivery constraints and advisory aesthetic judgments rather than making every stylistic preference a hard gate. Vision and narrative scaffolding must state what was actually assessed.

## Measured speed opportunities

Eight-second synthetic CPU fixture, not a production/model benchmark:

| Experiment | Existing median | Prototype median | Qualification |
|---|---:|---:|---|
| Trim + resize |1.324s|0.519s|2.55×; same geometry/codecs, but4.01s versus4.00s timing. Needs timing, loudness and quality acceptance |
| Ten thumbnail extractions |1.654s|0.265s|6.24×; all ten JPEG and decoded RGB hashes match this CFR fixture |
| Loudnorm analysis with video disabled |0.292s|0.184s|1.59× analysis-only; numeric measurement dictionaries match |

Fuse compatible filters into one encode; retain review/checkpoint barriers. Reuse verified media across platform packages when actual transformation identity matches. Batch dense frame requests; sparse seeking may win on two-hour sources. Retain selected source PTS instead of deriving timestamps from nominal FPS. Restrict scaling by output pixels and scratch bytes, stream bounded frames, preserve VFR and non-AAC audio. Fix cancellation before adding parallelism: current job cancellation drops runner identity while synchronous execution can continue.

A warm metadata lookup measured9.49µs versus raw subprocess79.6ms; this establishes redundant probing, not an end-to-end8000× speedup. Share validated facts and deduplicate concurrent misses with correct invalidation. Model sessions need bounded residency and safe ownership, not an unlimited global cache. Admission control must budget total FFmpeg/BLAS/ONNX threads, RAM, VRAM and temporary storage.

## Make the 2.6679% prose useful

That percentage measures authored source prose, mostly instructions read by the host agent. It does not measure inference, requests, cost or intelligence. The optimum can involve shorter prose.

1. **Fix discovery.** Actual tools/list:201 tools,209,272 UTF-8 JSON bytes. Substring search returns zero for7/12 illustrative queries; “captions” misses actual subtitle/transcription tools. Use deterministic aliases/token ranking, bounded results and schema-on-demand. An illustrative eight-tool core is11,578 bytes, about94.5% smaller metadata. Those are bytes, not measured tokens or savings; scoped exposure needs host support, not merely a search instruction.
2. **Progressively disclose instructions.** One compact inspect→plan→render→review workflow; load caption/matte/360 detail only for that task. Generate capability metadata from actual contracts to avoid contradictory skill lists and claims of unimplemented analyzers.
3. **Spend reasoning on meaning.** Use source-cited proposals for ambiguous intent, hook alternatives, complete-thought selection, contextual disfluencies and continuity critique. Retain before/after transcript context. Never invent first-person claims or let an unsupported request quietly become a15-second trim or the literal word CAPTIONS.
4. **Constrain and enforce.** Proposed actions reference existing source span IDs. Code checks span validity, budgets, names/numbers/negation, supported actions, timing, approvals and output identity. Untrusted transcripts/on-screen text remain data. Prompt text helps behavior; it is not authorization or a validator.
5. **Measure task outcomes.** Held-out paraphrases and difficult editorial cases, repeated runs: successful task completion, wrong/invalid tools, unsupported source claims, human corrections, calls/tokens, p50/p95 latency and total spend. A shorter prompt that increases wrong renders is more expensive overall.

A useful editorial instruction: “Propose only from supplied source spans. Cite the spans supporting each claim. Preserve qualifications, numbers and negation. Report missing evidence and unmet requirements. Return bounded alternatives with uncertainty; leave exact timing, execution and approval to code.”

## Enhance existing deterministic features with specialized ML

| Existing feature | Intentional enhancement | Required validation |
|---|---|---|
| Caption generation / cleanup | Evaluated ASR backend, anti-aliased frontend, VAD, optional aligner and contextual disfluency classifier | WER/CER, numbers/names, silence hallucination, word-boundary error, meaning-bearing false deletions, cold/warm latency |
| Reframe / subject-safe crops | Actual detector, tracker and optional active-speaker adapter feed existing typed planning evidence | Crop containment, track switches, staleness, velocity per second, occlusion; abstain on missing coverage |
| Semantic asset search | Verified embedding-space identity, BM25+vector fusion, small reranker only if needed | Recall/nDCG, no-match handling, model-version mismatch, query latency and memory |
| Highlight selection | Creator/session-held-out pairwise ranker over explicit preferences and source features | Acceptance@k, review time, meaning preservation; avoid invented virality probabilities |
| Caption translation | Real supported MT with cue context/glossary protection | Bilingual adequacy, negation/numbers/names, unchanged cue timing, reading speed |
| Product matte | Motion-warped prior masks, uncertainty/scene-triggered refresh, bounded rolling smoothing | Fine-edge alpha quality, flicker, transparent items, logo preservation, quality versus compute frontier |
| Visual review | Scene/audio/blur events + OCR/detectors guide bounded evidence; VLM only for unresolved semantics | Defect precision/recall, coverage, false pass rate, evidence citations, frames/tokens per job |
| Voice consistency | Real speaker embeddings and measured prosodic features | Same speaker/different text versus different speakers, noise/short-clip uncertainty and calibration |

Confidence labels must identify what the number means. Word length, hash distance, lexical score and cosine similarity are not automatically probabilities of correctness.

## Is a decision model a fourth kind of code?

It can be a fourth **operational lane**, not a new programming substrate:

- Deterministic code/DSP/optimization: exact transforms, geometry, timing, budgets, provenance and execution.
- Learned perception/retrieval: speech, faces, masks, embeddings and motion evidence.
- Learned decisions/ranking: select finite proposals, classify intent, estimate cost or prioritize review.
- Generative editorial reasoning: resolve ambiguity and produce source-grounded language/alternatives.

These lanes help architecture. They overlap model families: a decision model can be transformer-derived, and a speech model can be LLM-derived. Keep role, architecture, locality, determinism and cost as separate axes. For four percentages summing100%, reclassify the existing ML allocation into mutually exclusive buckets; never append a fourth percentage to the old three. Seeded decoding is not a guarantee of reproducibility across runtime revisions.

Candidate uses for a typed-decision model: intent classification over supported capabilities, reranking a small discovered tool set, choosing relevant source spans, flagging semantic-risk windows and identifying which uncertain candidates deserve deeper review. Code owns allowed options, evidence IDs and result validation; “abstain/needs context” is a real option. It cannot authorize publishing, prove facts, or fix poor timestamps. Compare against deterministic rules and a small supervised ranker as well as a general LLM.

For runtime/cost prediction, ordinary quantile regression or GBDTs may be preferable: learn stage costs from telemetry; deterministic scheduling respects quotas. For crop/shot choice, dynamic programming or constrained optimization can beat a learned policy without any training data. Adopt a contextual bandit only after offline evaluation, explicit bounded exploration and a protected sampling floor; training on the system’s own unverified outputs is not evidence of improvement.

## Jev: what changes in the design

Current primary source: [TypeSafe’s own documentation](https://github.com/typesafe-ai/skills/blob/65a39f393687675ce170e6094757de20370365b9/skills/typesafe-ai/SKILL.md), checked September30,2026. Jev is its first System One model, for semantic judgments rather than text generation. **Choice** selects offered options with a distribution; **Noul** returns P(yes); **Score** returns a distribution over described ordered levels and its expected score. Parallel questions share observed state but cannot see each other’s answers. A dependent question needs another request if it requires newly fetched evidence.

The useful architecture is `observations → bounded decision → code-validated action`, with generation added only when new language is needed. Start with explicit deterministic routing and cheap retrieval. Jev judges ambiguous intent or bounded retrieved candidates. General LLM handles grounded creative wording or complex unresolved reasoning. Maintain source IDs and explicit no-evidence/unsupported/needs-context options. This concentrates prose into reusable question rubrics instead of asking for repeated planning essays.

High-fit experiments:

- **Admissible operation and source selection together:** code enumerates executable workflow/asset options from current capabilities; Jev selects finite options; code rechecks freshness and arguments. Browser Use’s current integration demonstrates this decomposition; it calls a generative model only for freeform field text.
- **Source-span reranking:** cheap lexical/vector retrieval first, then judge relevance and completeness over a small set, returning original spans. Jevgrep already uses verbatim evidence selection; copy the pattern, not its benchmark headline.
- **Meaning-risk review:** assess standalone completeness, changed implications and lost caveats using before/after context. Deterministic protected-span failures remain mandatory. September’s jev-fidelity/jev-proof already implement text fidelity/brief checks; Kinocut’s bet is exact media/time-map/revision integration, not conceptual exclusivity.
- **Contextual disfluency:** judge rhetorical versus unwanted repetition over timed ASR proposals. Preserve speech on uncertainty; never let Jev invent cut times.
- **Reusable editorial dimensions:** cache source-bound rubric distributions; changing preference weights need not repeat inference. Approval remains a distinct exact-artifact human action.
- **Verbatim review-packet selection:** retain relevant optional evidence while pinning requirements, negative findings and approvals in code. Full immutable receipts remain available; compression never deletes authority or audit history.

Do not equate confidence concentration with correctness. Several valid choices can lower concentration; confident answers can still be wrong. Candidate omissions are retrieval failures. Calibration and selective risk/coverage matter more than a universal0.8 threshold. Jev does not transcribe audio, inspect raw pixels through this text contract, generate new copy, or authorize execution.

**Cost correction:** non-generative output does not guarantee a cheaper whole task. SDK snapshot says output tokens currently free; live input rate and billing remain unverified. More candidates/questions and duplicated evidence still cost input tokens. One public browser trace reports17 Jev calls with median178ms but excludes billed Jev/browser cost. Its25% task improvement is a same-stack runtime optimization on one task. A public Jevgrep10-task rerun reports25.8% total-cost savings, while a later variant increased combined cost2–3%. Other public integration notes report higher billed-input multiplication and higher estimated cost than compact LLM outputs. These are author measurements with small/unequal workloads, not our benchmarks. Measure real invoice cost per correct reviewed task, including retries and review effort.

**Locality correction:** official comparison adapters implement the same interface with general LLMs; they are not self-hosted Jev weights. Independent NanoJev/jevos models are separate, limited alternatives. We have not verified official Jev architecture, parameter count, open weights, context limits or retention/SLA. Evaluate hosted Jev only under existing cloud authorization; local-first workflows remain supported without it.

Shadow evaluation before adoption: current intent route, improved lexical retrieval, small local classifier/ranker, Jev and general LLM on the same held-out EN/ES briefs. Measure intent fidelity, unsupported abstention, grounded selection, meaning-damaging edits, Brier/ECE, selective risk versus coverage, user correction, p50/p95 latency and total$ per successful output. Record resolved model versions, rubric/source hashes, actual billed input and provider failures. No paid inference was run for this review.

## Feature bets worth testing

1. **Meaning-preserving clips.** Keep source context and protected qualifications; show counterfactual edit previews, source citations and what was removed. Measure misleading edit rate and editor preference, not a speculative viral score.
2. **Exact-artifact review.** Authenticated approve/reject decisions bind source, proposal and output identities; stale approvals are invalid. Existing preview UI provides video plus polling, not this complete approval experience.
3. **Private preference learning.** Opt-in local ranking from editor comparisons with creator/session-separated evaluation. Preferences never grant publishing authority.
4. **Compute-aware review.** Show evidence coverage, predicted processing cost and uncertainty; reuse transcripts/frames across platform variants. Spend expensive reasoning only where measured benefit justifies it.
5. **Evidence-driven360 lessons.** Track hands/product/speaker and rank finite approved camera plans; geometry and motion budgets stay deterministic. A larger investment after real perception adapters and review controls work.

These are differentiation hypotheses. Generic captions, clips, reframing and chat editing are not exclusive. Current September Jev implementations explicitly overlap editorial fidelity and transcript brief checking. Competitor product pages could not be comprehensively verified; do not publish “first/only/nobody has it” claims from older research or from this review.

## Order of work and acceptance

**First: restore trust.** Truthful capability/assessment states, remove invented voice scores, CAS restoration policy, color-unit correctness, output preservation and effective cancellation. Each has externally observable tests; mocked providers cannot certify perceptual accuracy.

**Then: reduce repeated work.** Audio-only loudnorm analysis; batched evidence; shared quality facts; narrow transport-free worker; measured render fusion with timing/quality constraints. Track encode/decode starts, scratch peak, wall time and cost per accepted output.

**Then: add decision and perception value.** Reuse the organization’s speech implementation once identified; benchmark contemporary alternatives; validate Jev on finite source-grounded tasks; complete tracking/MT adapters. No bulk model installs or heavy dependency changes are justified merely by a new model release.

**Then: preference and differentiated editorial features.** Annotation and held-out evaluation precede claims of better recommendations. Ship features only when measurable quality gains justify added latency, cost and failure modes.

Model-level gains are still experiments: no new weights were installed and no ASR accuracy, Jev API cost or production throughput was measured in this review. Source percentages are not an optimization objective.

## Evidence companions

- Architecture visual report: /tmp/architecture-review-20260930-084713.html
- Reliability reproductions: /tmp/kinocut-reliability-findings.md
- Latency measurements: /tmp/kinocut-latency-findings.md and /tmp/kinocut-latency/*.json
- Intelligence placement: /tmp/kinocut-intelligence-findings.md
- Product hypotheses: /tmp/kinocut-product-findings.md
- Current official ASR sources: /tmp/kinocut-current-asr-research.md
- Actual discovery results: /tmp/kinocut-discovery-evidence.json

- Exact Jev primary-source research: JEV-RESEARCH.md
- Current Jev implementation/product comparisons: /tmp/kinocut-jev-product-findings.md

- Jev latency/cost evidence and caveats: /tmp/kinocut-jev-cost-findings.md

For a Jev→LLM cascade at equal quality, model-only expected cost is C_J + e*C_L, where e is the escalation fraction. It beats always-LLM only when C_J < (1−e)*C_L; network, retries, review and wrong-render costs must also be included. Adding Jev ahead of an already-correct deterministic path adds cost.
