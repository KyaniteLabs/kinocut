# External-report follow-up and CI repair — 2026-09-30

This checkpoint follows the [banked implementation](../pr-checkpoint/validation.json)
and [GitHub backlog review](../../github-backlog/2026-09-30/REPORT.md).
[PR #586](https://github.com/KyaniteLabs/kinocut/pull/586) contains the combined
work. The [external-report ledger](../../external-ai-audits/2026-09-30/REPORT.md)
distinguishes verified recommendations from stale or unsupported assertions.

## Changes

- Shared FFmpeg errors identify complete missing-encoder/filter diagnostics and
  attach bounded dependency advisories. They retain `ProcessingError` compatibility,
  full stderr and the exact requested name; there is no automatic codec fallback,
  filter substitution or installation. Real-FFmpeg and serialization tests cover
  false positives, case-sensitive names, Unicode and input-error precedence.
- Host guidance uses explicit MCP stdio commands, adds source-verified native
  Gemini CLI setup and separates experimental SDK support from other host products.
  The new `docs/llms-full.txt` supplies operational context on demand rather than
  duplicating installed schemas. Host egress, costs and human review remain explicit.
- Live evidence corrects stale claims about missing site JSON-LD/FAQ and package
  identity. Canonical publication metadata is 1.15.3 / shim 1.6.14, while GitHub
  latest release remains 1.15.0 and registry verification is unavailable. No package
  version, dependency pin, website deployment or public tool count was changed.
- Pinned Ruff 0.15.11 reproduced the original head's hosted Lint failure. Formatting
  repairs preserve executable ASTs; four docstring lines were compacted to retain
  architecture size limits. The exact CI lint/format commands pass locally.
- The hosted grayscale failure was reproduced with primary FFprobe 6.1.
  Gray-only full-range input metadata makes native-depth measurements consistent
  with FFprobe 7.1.5; ordinary YUV measurements are unchanged. Source metadata
  caching is shared with audio-stream checks and rejects unusable observations.
  The [converter matrix](grayscale-version-review.md) and
  [hosted investigation](../../external-ai-audits/2026-09-30/HOSTED-TEST-INVESTIGATION.md)
  retain the evidence and first-probe latency tradeoff.

## Evidence and remaining opportunities

| Authored runtime source | Share |
| --- | ---: |
| Deterministic code | 96.9336% |
| Operational LLM prose | 2.6366% |
| Traditional/non-LLM ML integration | 0.4298% |
| Total | 100.0000% |

[Allocation](allocation.json) inventories the frozen runtime tree; source shares
are neither execution cost nor measured product quality. Host skill prose is
reported separately. [Final validation](grayscale-validation.json) and [full log](grayscale-full-suite.log)
record 7,429 passed, 185 skipped and 8 warnings in 938.46 seconds.
[Earlier validation](validation.json) preserves the preceding checkpoint;
focused and repeated counts are not additive.
Real MCP stdio initialization, listing 201 tools and metadata-only `search_tools`
discovery passed without a model call. This does not establish a paid host roundtrip.

The earlier ASR and Jev research remains applicable. No replacement model was
installed or benchmarked; the organization's deployed ASR identity is unconfirmed.
Typed semantic decisions can propose bounded routes or ranked spans, while code
continues to enforce exact timing, source identity and execution authority.
Next experiments need representative caption/editorial fixtures and calibrated
abstention, word-boundary accuracy, accepted-result cost and cold/warm latency.
Remaining engineering opportunities include bounded signalstats parsing and
anti-aliased ASR resampling; they need behavior and resource measurements before
changing execution. This PR does not claim that every optimization is exhausted.
