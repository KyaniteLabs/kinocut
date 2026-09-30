# Implementation checkpoint — 2026-09-30

Subsequent GitHub issue/PR adaptations are recorded in the [backlog report](../../github-backlog/2026-09-30/REPORT.md). The allocation artifacts are refreshed for the combined working tree; the tests below remain the earlier checkpoint.

This checkpoint follows the architecture review and current ASR/Jev research.
Changes remain local and uncommitted. The initial allocation is a historical
baseline; `allocation.json` here describes the current working tree, including
new unignored runtime modules. These are authored-source proportions, not
inference cost, latency, execution frequency, or model weight proportions.

## Current source allocation

| Category | Share |
| --- | ---: |
| Deterministic code | 96.9286% |
| Operational LLM prose | 2.6409% |
| Traditional/non-LLM ML integration | 0.4305% |
| Total | 100.0000% |

The inventory covers 624 runtime files and 1514 tracked or unignored working-tree paths. Host skill prose is reported separately. Jev contributes no runtime source because no provider has been integrated.

## Changes retained

| Area | Result and verification |
| --- | --- |
| Tool discovery | Exact names remain first; whole-phrase aliases connect seven previously empty natural-language searches to the intended tool. Unrelated queries still return no matches. No learned classifier or network request is needed. |
| Host instructions | Ground creative proposals in source evidence; preserve names, numbers, qualifications and negations; distinguish planning from executed inference. Workflow instructions now match supported operations. |
| Vision review | Frame extraction no longer claims semantic evaluation. Missing inference is `not_evaluated`, incomplete sampling is `inconclusive`, and required-but-unavailable inference blocks. SDK installation alone is not model availability. |
| Voice continuity | Remove hash-derived pseudo-similarity. Unconfigured style and identity inference is unavailable; exact-byte hashes remain integrity evidence. |
| Quality cache | Cache only successful, nonempty observations of unchanged source identity and analysis window. Failed measurements retry; replacement files invalidate cached results; retained entries are bounded. This is not a cryptographic integrity boundary. |
| Black coverage | Weight decoded presentation intervals, including the terminal frame and sub-log-threshold black spans. VFR and longer audio tracks do not distort coverage. Corrupt or unverifiable decoding is unavailable; metadata and diagnostics stream through managed temporary files. |
| Sample units | Normalize native 8/10/12/16-bit SDR luma/chroma and full/limited range before applying 8-bit thresholds. Negotiate motion differences before grayscale conversion to avoid an artificial black offset. HDR delivery acceptance remains unevaluated. |
| CAS lifecycle | Preserve immutable manifests and GC history while supporting verified re-import. Record repair intent/completion, validate backup ownership, and reclaim interrupted-repair backups. Verify actual bytes before reporting availability. |
| Conversion | Render and validate a staged file before publishing. Callback failure, timeout or failed postflight preserves an existing destination; source and hardlink aliases are rejected. This does not make every other engine writer transactional. |
| Detached cancellation | Persist stop intent and retain the runner PID until process-group quiescence and released job lease confirm completion. Unverified identity or timeout remains pending; queued cancellation is immediate. Completion cannot overwrite a stop request. Reconciliation also requires observed quiescence and no held lease, rather than orphaning live work by default. |
| Audio analysis | Analysis-only FFmpeg passes explicitly disable video processing. Real loudness and silence fixtures preserve results; ordinary delivery still retains intended streams. |
| Waveform | Return measured RMS rather than accidental synthetic fallback. Tests cover silence, offsets, final partial windows and opposite-phase stereo; aggregate means use linear power. Legacy fallback remains explicitly labeled. |
| Runtime reuse | Load ASR once per longform job; reuse voice features per roster; bound pitch windows; stream file hashes; vectorize PCM parsing and pixel counting. Equivalent-output fixtures and local benchmarks accompany these changes. |

## Architectural direction

The [architecture review](architecture-review.html) applies Matt Pocock's
`improve-codebase-architecture` skill to this checkout, with five concrete
before/after boundaries. The review predates implementation: consult this
checkpoint for fixes already landed locally. CAS lifecycle and tool discovery
are bounded internal modules; public facades remain intact. A broad module
reorganization was not necessary to fix these behaviors.

The next useful boundary is a shared, typed quality-evidence interface:
measured, evaluated, unavailable and inconclusive states must remain distinct.
Detached execution should ultimately depend on an engine service rather than
calling an MCP transport handler. Transactional publication should extend to
remaining writers after validating each operation's timing and output contract.

## Models and product opportunities

[Jev research](JEV-RESEARCH.md) identifies TypeSafe AI's typed semantic decision
model, not JEPA. Use four operational lanes: deterministic execution,
perception/retrieval, semantic decisions, and generative proposals. These lanes
are not four mutually exclusive mathematical model families, and Jev is not
currently integrated. Candidate uses are bounded intent routing, retrieved-span
ranking, context-loss proposals and editorial rubrics. Code still owns exact
media timing, hashes, admissible operations and approval. Confidence requires
calibration; it does not authorize execution.

[ASR research](ASR-RESEARCH.md) covers current Nemotron streaming ASR, Parakeet,
Canary, Qwen3-ASR and Moonshine. No replacement weights were installed and no
quality comparison was run. Streaming accuracy alone does not establish word
timestamp suitability for editing. The organization's recently adopted backend
was not identifiable from this checkout; its identity remains an open input.

The strongest product bet is editorial fidelity tied to exact media revisions:
pin critical source spans, show proposed deletions and retained qualifications,
then invalidate decisions when underlying assets change. Competitors already
offer transcript/brief fidelity tools; the evidence does not support an
exclusivity claim. Exact timing, revision provenance and review integration
are the proposed differentiation.

## Evidence and limits

The full-suite checkpoint passed **7,135 tests, 183 skipped**, before the last
conversion, cancellation and quality-measurement changes. After all code changes were frozen, the combined **63 affected test modules
passed 925 tests, with 9 skipped**, in 95.46 seconds. This is a separate run,
not an additive total or a claim that the full suite covered the last changes.
Ruff, diff checks, canonical/compatibility imports and `kino doctor` pass.
All 1,097 working-tree Python files parse; parsing is not behavior validation. Tests skipped for unavailable
dependencies are not proof that optional models work.

Local synthetic CPU fixtures show roughly 3–15× roster-feature speedups,
8.7× pixel counting, 35× PCM parsing and lower streamed-hash memory. These are
microbenchmarks, not production latency guarantees. See
`optimization-benchmarks.json`, `audio-analysis-equivalence.json`,
`silence-analysis-equivalence.json` and `conversion-preservation.json`.

The next model experiment needs a labeled representative media corpus,
approved model/backend access, target hardware and cost limits. Compare name
and number accuracy, silence hallucinations, word-boundary error, editorial
acceptance, calibrated abstention, cold/warm p50/p95 latency and cost per
accepted result. No model selection, LLM quality gain or end-to-end savings is
claimed from source share or vendor benchmark claims.
