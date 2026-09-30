# Further research: newer ASR and learned decision/world models

Read-only repository/official-primary-source investigation, 2026-09-30. No model installation/download, third-party code execution or repo edits. Public source repositories fetched through existing Git HTTPS access. The organization's ASR deployment is not identified in this checkout. Jev was subsequently identified as TypeSafe AI’s System One decision model; see JEV-RESEARCH.md for the verified interface and assessment.

## What is actually in Kinocut

A /workspace markdown/Python/package search found no implemented Parakeet, Canary, Moonshine, Qwen-ASR, Voxtral, FunASR or JEPA adapter. `docs/superpowers/specs/2026-07-11-kinocut-sound-sonic-world-design.md:432` specifies local faster-whisper-class ASR; that is an architectural plan, not executable integration. Org references in `docs/local-first/COMPAT-MATRIX-SPEC.md` concern Qwen language-model inference, not a new ASR implementation. Thus an organization-wide successor cannot be identified from this checkout alone. Reuse that implementation once user/repo search identifies it; do not independently rebuild yet another ASR stack.

Three existing ASR consumers should share one result contract:
- `kinocut/ai_engine/transcribe.py` direct openai-whisper adapter (loads model per short call).
- `kinocut/ai_engine/_longform_runtime.py` same backend with per-job cached model and word timestamps.
- `kinocut_sound/public/asr_worker.py` isolated cached-checkpoint CPU worker; `asr_request.py` limits schema-v1 to base/base.en and EN/ES; `asr_runtime.py` validates package registry and model digest, stages an already-cached verified model. This safety mechanism must survive backend abstraction, not be replaced by automatic from_pretrained downloads.

Additional quality concern: sound ASR worker currently resamples PCM with `np.interp` without an explicit antialias low-pass filter. At downsampling this can alias high-frequency noise into speech band and hurt recognition. Evaluate reuse of the repo's verified FFmpeg/libsoxr resampling path (or a separately pinned polyphase filter) with known sine/noise fixtures and speech WER; retain sample accounting/hash provenance. Do not assume better ASR weights fix frontend quality. Current word comparison is bounded deterministic NFKC/casefold/alnum-v1 and records Unicode version; preserve/report normalization when comparing model outputs to avoid attributing punctuation/number-formatting changes to recognition accuracy.

## Primary sources and candidate comparison

Official snapshots fetched:
- NVIDIA NeMo URL redirects to NVIDIA-NeMo/Speech; SHA `00278b0bd95bb2b8174b88012aa21b003c59d2e9`: https://github.com/NVIDIA-NeMo/Speech
- Qwen3-ASR SHA `7c6daf77a2421100f5fb066495372c00129d39ff`: https://github.com/QwenLM/Qwen3-ASR
- Moonshine SHA `234f60faa0eb388b01cdf7e60aca232af37aefda`: https://github.com/moonshine-ai/moonshine (old usefulsensors URL resolves here).

These are source documentation claims, not Kinocut benchmark results. Exact deployed weight artifacts, corresponding weight licenses and runtime revisions must be verified before integration. Repo license alone does not establish every model's license. An attempted presumed mistralai/voxtral GitHub repository does not exist; no Voxtral details were invented from that failed lookup.

| Candidate | Documented capability | Fit / qualification |
|---|---|---|
| Parakeet-TDT-0.6B-v3 | NeMo docs: 25 European languages, auto language detection, punctuation/case, word/segment/character timestamps; offline/longform/streaming options. | Strong EN/ES bulk caption candidate; timestamps particularly relevant to cleanup cuts. TDT/CTC family specialized ASR. GPU recommended for NeMo inference; CPU implementation/performance must be measured on target host. Not speech translation. |
| Parakeet-unified-en-0.6b | Apr2026 NeMo README: offline + streaming English, min publisher-described latency 160ms, punctuation/capitalization. | English preview/live workflow, not Spanish coverage. Chunk latency is not complete end-to-end task latency. |
| Canary-1b-v2 | Aug2025 release; NeMo docs 25 European languages, speech recognition and translation, AED, timestamps and longform. | EN/ES+speech-translation candidate; speech translation differs from translating existing editable SRT cues. Keep transcription and translation provenance separate. |
| Nemotron-3.5-ASR-Streaming-0.6b | June2026 NeMo README: 40 languages, cache-aware FastConformer, controllable 80ms–1s latency and 240–2400 concurrent streams on 1xH100 depending mode. | Recent candidate for actual live captions/interactive timeline. H100 throughput is not single-job speed on this machine, and live need may be absent. Relevant current alternative beyond the 2025 models. |
| Qwen3-ASR-0.6B/1.7B | Jan2026; 30 languages +22 Chinese dialects (not 52 distinct national languages), language ID, longform/offline+streaming. Separate ForcedAligner-0.6B supports 11 languages incl EN/ES. June2026 native Transformers support. | Multilingual/noisy/music-backed transcription candidate, particularly if already implemented by org. Official ASR is Qwen3-Omni-derived and framework uses LLM APIs; specialized task does not make architecture non-LLM. Offline timestamps add forced-aligner memory/latency. README: streaming currently vLLM only, no timestamp or batch return; cannot substitute streaming text for timed-cut contract. Apache-2.0 repo; validate exact weight card. |
| Moonshine Voice | Current docs: on-device cross-platform ONNX/ORT streaming models; EN Tiny/Small/Medium 34M/123M/245M, Spanish Small/Tiny streaming; opt-in word timestamps need auxiliary attention/alignment assets; speaker spans optional. | Attractive CPU/mobile low-latency preview path; compare full-file throughput as well. Streaming models MIT; legacy nonstreaming Spanish Base is Community noncommercial. Exact model architecture/license matters. Current toolkit evolved substantially from old tiny/base-only implementation. |
| Faster-Whisper/CTranslate2 (existing planned family) | Alternative execution stack for Whisper weights. | Useful control baseline for precision/runtime improvements, but not a new speech architecture and not automatically best. No new primary-source snapshot fetched for this item. |

NeMo official code currently targets Python>=3.12, PyTorch>=2.7, recommended CUDA GPU, tested stacks as new as CUDA13; keep isolated optional runtime/container rather than force core Kinocut users onto heavy dependencies. The docs' choosing-a-model page itself has a suspicious 'Parakeet-TDT V3' hyperlink to a different 1.1b ID: use exact checkpoint ID/model card rather than blindly follow recommendation prose.

Qwen publisher 2000x throughput is at concurrency128; it is not a latency guarantee. Moonshine official benchmark doc explicitly says its CPU phrase endpoint latency benchmark models live 1–10s speech, not bulk offline throughput. It also says deployed quantized English metrics differ from float-reference leaderboard metrics. Its benchmark description calls processing-time/audio-duration an inverse RTF, although that ratio is ordinarily RTF; normalize metric definitions in our own harness rather than copy names. Do not choose model by averaging incomparable leaderboard/dataset/hardware numbers.

## Shared ASR port and evaluation plan

Define `ASRCapability{backend_id, runtime_version, weights_digest, supported_languages, word_timing, streaming, speaker_spans, devices, max_window, network_requirement}` and immutable `ASRResult{source_hash, frontend_profile, language, spans, words?, confidence_kind?, provenance, cost, warnings}`. Model-probability and alignment-confidence fields cannot be silently equated across backends; preserve kind/calibration metadata. Keep original observed text separate from editorial corrected text. Adapters never quietly claim precise times when unavailable; aligner is separately declared capability and expense. Runtime authority remains code.

Central chunk planning, EOF clamps, subtitle rendering, caching, validation and receipts remain backend-neutral; each provider implements only inference/optional alignment. Cache key includes every frontend/model/decode/aligner choice; hot-swap backend invalidates evidence rather than reusing misleading cached predictions. Offline-only existing-weight policy, integrity checks, no arbitrary remote_code, total deadline, bounded output and isolated model deserialization retained. Versioned schema supports old base/base.en clients without changing old receipt semantics.

Benchmark small representative EN/ES suite including noise/music, silence hallucination, accented speech, speaker overlap, domain names/numbers, code switching, variable source rates and short/long clips. Measure WER/CER with defined normalization, named-entity and number error, word-boundary p50/p95, critical false deletion rate in generated cut proposals, cold initialization/warm RTF, first partial/final stabilization for live mode, peak RSS/VRAM, hardware energy and total cost. Include cancellation, missing weights, malformed provider output, changed model digest and no-network failures. Prefer a Pareto frontier selected by task constraints: best editing timestamps, best CPU latency, multilingual coverage, lowest cost; retain known reliable fallback rather than universal replacement.

## Learned decision models: a separate operational role

A fourth engineering lane could be **learned ranking/policy models**, but mathematically it is a subset of non-general-purpose ML. To make four categories add to 100%, reclassify old ML files and define exclusivity; do not add a fourth percentage to unchanged previous numbers. Better measure architectural family, operational role, locality, determinism and spend separately. ASR transformer/token decoding is not automatically a general editorial LLM; Qwen-ASR being LLM-derived is equally not 'traditional statistics'.

Start with simpler intentional policies:
- Runtime/cost estimator (ridge/GBDT/quantile regression) predicts actual render/model time from media/codec/GPU features; scheduler deterministic with quotas/quality budgets and OOD fallback. Measure p90 prediction intervals, deadline misses and GPU/CPU cost versus baseline; training requires runtime telemetry, never approval labels.
- Candidate pairwise ranker learns explicit editor accept/reject/compare decisions. Small logistic/GBDT first; split by creator/session to prevent leakage, check calibration and distribution drift; frozen score does not equal content quality certification. Measure acceptance@k and review time, preserve rejected-but-valid alternatives.
- Adaptive analysis controller chooses where more ASR/VLM/detector evidence has value under a bounded budget. Begin deterministic uncertainty thresholds; a contextual bandit can follow only with offline evaluation, opt-in bounded exploration and protected uniform sample floor. Avoid substituting accuracy for no-op savings or training on its own unverified predictions.
- Crop/shot selection policy can rank finite geometry options, but deterministic constrained optimization (dynamic programming, beam search, MILP) is often better: confidence/crop loss/velocity constraints are explicit, no training dataset required. ML estimates uncertain perception; solver executes the policy. This is code/optimization, not a new ML type.

Evaluation of learned policies needs comparison to heuristics, simple predictive model, specialized vision encoder and general LLM; measure benefit per annotated example/GPU-second as well as quality. The separate JEV-RESEARCH.md assesses the verified TypeSafe interface and its fit for these bounded decisions. Differentiator hypothesis: source-faithful motion-semantic search and review that spend compute only where evidence is uncertain, with exact explanations and edit provenance. No competitor-absence claim has been established.

## Pinned primary-source links

- NeMo overview/new releases and requirements: https://github.com/NVIDIA-NeMo/Speech/blob/00278b0bd95bb2b8174b88012aa21b003c59d2e9/README.md
- NeMo timestamp contract: https://github.com/NVIDIA-NeMo/Speech/blob/00278b0bd95bb2b8174b88012aa21b003c59d2e9/docs/source/asr/inference.rst
- Qwen release/capabilities and streaming restrictions: https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/README.md
- Moonshine model/language/license table: https://github.com/moonshine-ai/moonshine/blob/234f60faa0eb388b01cdf7e60aca232af37aefda/docs/models/available-models.md
- Moonshine word timestamp/auxiliary assets: https://github.com/moonshine-ai/moonshine/blob/234f60faa0eb388b01cdf7e60aca232af37aefda/docs/api/c-api.md
- Moonshine benchmark scope/caveats: https://github.com/moonshine-ai/moonshine/blob/234f60faa0eb388b01cdf7e60aca232af37aefda/docs/using/benchmarks.md

Current recommendation: identify/reuse the organization ASR implementation, expose it behind a bounded verified adapter, and evaluate Parakeet v3 for EN/ES offline word timings; Moonshine EN/ES streaming for portable CPU previews; Qwen3-ASR plus separately budgeted alignment for wider multilingual/noisy recognition; Nemotron3.5 only when live streaming is actually needed and target hardware supports it. Preserve existing Whisper path as control/fallback until required media-quality/timing benchmarks demonstrate an improvement. JEV remains unresolved; no capability, architecture or integration recommendation for JEV is asserted.
