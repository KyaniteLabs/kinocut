# Jev: corrected identification and Kinocut fit

Research date: 2026-09-30. **JEV means TypeSafe AI's Jev/System One decision model. It is not JEPA.** Earlier JEPA speculation is superseded and must not appear as the answer to this request.

## Verified primary-source identity and interface

TypeSafe's own skill calls Jev its flagship and first System One model. It understands natural language/state and returns typed judgments and probabilities **rather than text or reasoning explanations**. This is a decision interface, with deterministic code owning workflow and enforcement. Primary source:
https://github.com/typesafe-ai/skills/blob/65a39f393687675ce170e6094757de20370365b9/skills/typesafe-ai/SKILL.md

The official Python SDK proves a functioning documented API contract, not merely ecosystem marketing:
https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/README.md
Generated wire schemas (from official api.typesafe.ai/openapi.json):
https://github.com/typesafe-ai/typesafe-sdk-python/blob/f078f1e208a0d885154dc758344ae4fce77ac168/src/typesafe_sdk/_schemas/models.py

Request POST `/v1/systemone`: model, structured/string state, question map. GET `/v1/models` supports current account models/release metadata. Examples name `jev-latest`; the schema example release_date `2026-09-15` is **an example**, not verified actual release date. For reproducible evaluation use resolved actual model/version, not silently mutable alias; current available versions require authorized read-only model listing or live docs.

Primitives:
- **Choice**: selects one offered candidate, returns full candidate distribution and concentration/confidence. Include no-match/need-more-evidence options where justified.
- **Noul**: returns P(yes), no separate confidence field. P=.5 is uncertainty between yes/no, not medium semantic intensity.
- **Score**: described ordered levels; returned score is probability-weighted average, distribution and confidence. This supports rubric ranking without freeform generation.

Independent questions share state and run in parallel; they cannot observe each other's answers. Ask useful speculative branch questions together, consume only relevant branch. A later request is necessary if first result is needed to fetch new evidence or build candidates. IDs are only for code, not semantic meaning fed to model: criteria/instructions must fully define task. Extra questions still consume tokens; one request is not zero cost.

Official skill explicitly warns: concentration confidence does not certify entire workflow correctness or permit action; typed answers ensure interface, not truth. Calibrate thresholds on target data/consequences. Several acceptable alternatives can lower confidence without an actual defect. Questions depend on candidate/evidence coverage: omitted source span cannot be selected. Separate policy rules from judgment values.

## Architecture knowledge and limits

We verified *operational interface* and description as a specialized learned decision model, not a conversational generating model. The reviewed official repositories do **not** disclose exact Jev parameter count, neural architecture/training recipe or open weights. Do not infer these from third-party replicas or claim native non-autoregressive implementation details unsupported by official material. It remains learned inference, not deterministic truth or handwritten conditions.

Official TypeSafe `system-one-adapter-python` provides a comparison adapter using OpenAI/Anthropic/Gemini LLMs to implement the same interface. It is NOT official Jev weights or self-hosted Jev:
https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/README.md
The adapter records cumulative tokens/retries/latency, offers distribution versus discrete answer modes and provider structured outputs; useful benchmark control. Prompted LLM probabilities are not inherently calibrated; normalization repairs sums, not correctness.

Direct TypeSafe website/blog/live docs are blocked by network proxy403 (verified with supported CA trust, verification kept enabled). GitHub public HTML search and Git source access succeeded. Therefore official current pricing rate, blanket latency, model weights/self-host plans, data retention/SLA and context limits could not be established. No paid Jev API calls, credential requests, private content uploads or third-party code execution occurred.

SDK Usage schema: billable input tokens; output tokens described as currently free. This is a *pinned snapshot statement*, not a verified live invoice rate. Do not promise lower total cost before token/latency/task-quality evaluation. Input state, candidate rubric definitions and parallel questions are costs too; oversized candidate lists may erase any savings.

## Real public integration illustrating intended separation

Browser Use × TypeSafe `jev-ultrafast` consumes current structured DOM state and finite compatible actions. Jev selects operation/target heads in one request; a small LLM is called only for freeform `TYPE_TEXT`. Code validates choice/distribution, target freshness/coverage, and executes observed nodes. DONE still requires independent result verification:
https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/README.md
https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/model.py

Publisher measurement: one Google Flights video 7,073ms; six alternating runs/three repeats per version medians 9.450s ->7.092s, protocol calls1092 ->101, both3/3 pass. README expressly says one task/profile is not general reliability benchmark. This demonstrates decomposition, not Jev's standalone latency, competitive universality or Kinocut performance. Browser protocol batching/freshness improvements also contribute.

## Ranked intentional uses inside Kinocut

1. **Semantic intent routing + parameter/source selection (highest immediate fit).** Current `intent/router.py` exact-verb mapping stays zero-cost deterministic for explicit structured requests. Current `te/goal_cutfile.py` keyword heuristics silently write CAPTIONS/first15s fallback. For ambiguous natural-language goal, use a Choice over *actually executable* workflows plus unsupported/clarify; optional Choice over finite ASR span IDs, existing assets/brand-kit values, valid aspect/platform choices. Code parses numeric durations, validates timeline/source hashes/capabilities, compiles and previews. If required argument cannot be selected from observed values, stop/clarify or escalate to editorial LLM; don't manufacture it. Independent intent/known-layout/fixed-option branches may share request. No inference for `trim start=5 duration=10`.

2. **Reranking source evidence/tools instead of long agent deliberation.** Current `search_tools` literal substring misses7/12 queries; fix cheap aliases/BM25/capability filtering first. Jev reranks only top bounded tools/spans, Choice when only one valid answer, per-candidate Score for graded relevance where multiple matches matter. Retrieval source IDs stay authoritative. Evaluate recall@k, invalid-call rate and tokens/call/wall latency against BM25, embeddings/cross-encoder and prompted general LLM. If cheap retrieval already meets success criterion do not spend on Jev.

3. **Semantic clip completeness/relevance rubric without copy generation.** Existing `product/highlight_discovery.py` bounded complete-thought windows, context, SourceSignal/SelectionExample contracts are suitable. Ask narrow Scores: relevant to goal, independently understandable, premise/context loss; Nouls for whether clipping reverses a negation or drops required context. Use existing transcript before/after; retain source-span references. This is editorial proposal ranking, not asserted factual proof; low certainty goes review. Deterministic duration/caption speed/loudness safety remains code. LLM only writes user-requested grounded title/creative copy; deterministic extraction returns verbatim title when enough.

4. **Contextual disfluency ambiguity.** Existing `semantic/disfluency.py` detects repeated <=4-token patterns and fillers. A Noul/Choice can distinguish rhetorical repetition and meaningful discourse from unwanted filler using bounded context; ASR/VAD timings remain specialized-model evidence. It ranks cut *proposals*, never authors arbitrary cut times. Require high measured precision in meaning-bearing false-deletion hard cases; near boundary uncertainty preserves speech. Compare trained small token classifier/cross-encoder before introducing cloud model.

5. **Grounded QA triage/extraction from existing evidence.** Ask fixed rubrics over transcript/OCR/tool findings, whether proposed caption is supported by source segment, whether remaining missing evidence warrants host-agent/human review. Actual vision `watching/vision_qc.py` currently only extracts3 keyframes; Jev text interface does not magically analyze raw pixels. Detector/OCR/VLM must create observed evidence first. No model alone closes release/consent/rights gates. Correct vision not-evaluated statuses first, regardless of Jev.

6. **Reusable preference dimensions rather than repeated full LLM planning.** Score stable bounded editorial dimensions once, preserve question/model/state version and raw distributions. Code recomputes preference weights interactively without another call. User approve/reject remains a separate exact-artifact action; user preference labels can train local ranker later. Publish cost/latency and quality comparison; no 'viral score'.

7. **Narrow inference escalation router.** Noul/Choice can recommend whether a semantic task needs more evidence/creative generation rather than using general LLM every time. Objective current capabilities/budgets/locality rules checked first in code; low-quality evidence never triggers unapproved cloud fallback. Avoid Jev network request just to decide if request can tolerate Jev network request.

Bad fits: FFmpeg construction, resampling, scene pixel differences, arithmetic/time windows, exact hashing/path/approval checks, loudness/compliance computation, speech transcription, new hook text itself. These are code/perception/generation jobs respectively. Jev is the conditional semantic layer *between* evidence and typed actions, not a replacement for the complete intelligence stack.

## Four-lane architecture and original percentages

Four *operational roles* make sense:
1. handwritten deterministic code/DSP/constrained optimization;
2. specialized perception/retrieval models (ASR/VAD/detection/matte/embeddings);
3. semantic decision models (Jev or evaluated calibrated local alternative);
4. generative/long-form reasoning LLMs for new grounded prose and genuinely complex editorial reasoning.

Jev's criteria/instructions are still prose. Model invocation is still code. Therefore 2.6679% authored prose does not tell us runtime share in role3 or4. Add role-aware invocation inventory and cost attribution. Any four percentages must be re-audited with mutually exclusive definitions (role3 currently no Jev implementation found); do not simply append role3 to old code/prose/ML shares. A neural decision model is part of ML mathematically, but deserves an engineering lane because interface/cost/design pattern differs from ASR and freeform generation. Avoid claiming classifier determinism implies truth.

## Local alternatives: examples, not interchangeable Jev weights

- **NanoJev** (independent) Qwen3-0.6B backbone + dynamic candidate heads, probability distributions without answer-token decoding; released checkpoint trained on four games. September20 README reports one model mixed game test results, including superior shooter tasks but maze4/10 vs Jev7/10. Not demonstrated calibrated Kinocut editorial model; weights/dataset/license need independent checks. https://github.com/TianyuCodings/NanoJev
- **jevos** (independent) llama.cpp/CPU yes-no compatible server. README local50–220ms, unseen-policy benchmark jevos0.811 vs Jev0.927; only Noul, rejects Choice/Score; criteria accepted but not read, so not drop-in semantic contract parity. No local equals hosted confidence claims. https://github.com/feder-cr/jev

Their performance is project-reported and unreplicated here. Could evaluate existing org-hosted local decision implementation if present; do not select gaming-tuned weights as general editorial default. Retain explicit backend capability matrix.

## Evaluation and privacy contract

First shadow mode on user-approved synthetic/public EN/ES tasks: no auto-execution and no private media egress. Compare deterministic lexical baseline, existing general LLM, Jev and suitable local classifier across paraphrase/negation/missing evidence/multiple valid choices/unsupported operation/adversarial source text. Ground truth must be independent human-reviewed labels; Jev judging itself is not evidence.

Metrics: route accuracy, unsupported abstention, source span grounding, intent fidelity, top-k ranking/human acceptance, calibrated selective risk-versus-coverage, Brier/ECE, meaning-damaging deletion rate, required human corrections, retries and p50/p95 end-to-end/cost per completed task. Set acceptance gates before comparing; no universal0.8 confidence threshold. Freeze task suite/model alias resolution/question rubric version, repeat trials, record input/question tokens and actual model IDs. Raw distributions separate from source reliability/decision authority.

For production proposed provider port: structured bounded state/questions, frozen decision trace, max input/question/candidate budgets, explicit model/cost cap/deadline/cancellation, source+question hash caching, output membership/finite-range/distribution validation, provider unavailable->no inference or explicit existing fallback. Code executes allowed actions only against still-current exact artifact. Cloud Jev requires explicit opt-in and exact egress manifest/data-retention review; availability never expands scope. Interface adapters shield core users from optional SDK dependencies; failure does not silently promote an edit or a release.
