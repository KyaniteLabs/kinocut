# PR validation and publication scope

[PR #586](https://github.com/KyaniteLabs/kinocut/pull/586) reviewed branch
`codex/kinocut-reliability-and-backlog` against `master`. The user authorized
commits, branch pushes, PR creation and subsequently merging #586 after its
corrected head passes review and checks. Draft contributor PRs were reviewed and
adapted, not merged. See the [backlog dispositions](github-backlog/2026-09-30/REPORT.md),
[external-report action ledger](external-ai-audits/2026-09-30/REPORT.md) and
[Unreleased changelog](../../CHANGELOG.md).

## Merged delivery checkpoint and separate UltraQA work

Fresh read-only GitHub metadata confirms #586 merged on **2026-09-30 at
21:50:42 UTC**, head `a6ff3ad3bb186f3f3f63900c7150da9a1ee025bf`, merge commit
`e9f6cac77cb390c73c919bdcd385b775a6a3c7ef`, tree
`44806e24c1e937040f1fe4c8471ece7aca979ad9`. All **13 checks** completed
successfully for that exact head, including hosted PR checks and staged runtime
jobs. [Delivery metadata](runtime-allocation/audio-timeline-ci/merged-delivery.json)
retains check names, exact SHA and links. Earlier failing heads below remain
historical; their results are not inherited by the final head.

The subsequently requested [whole-repository UltraQA gauntlet](ULTRAQA_GAUNTLET.md)
starts from this merged tree. Its working-tree changes and upcoming gates are
separate from the already successful delivery and published package.

The independent four-case native-six attribution was corrected after merge;
[the supersession record](runtime-allocation/audio-timeline-ci/corrections/supersession.json)
binds actual binary paths and source hashes. Its corrected mixer source differs
from the merged baseline. It does not invalidate the separately selected native
37-case suite, native eight-case matrix or genuine hosted FFmpeg-six CI.

## Final audio-fixture CI correction gate

Implementation `62c4948` corrects the hosted fixture's timestamp assumption;
production runtime remains unchanged from `cfdf03a`. The required full suite
passed **7,451 tests, 185 skipped, 8 warnings** in 940.71 seconds, exit 0.
[Result](runtime-allocation/audio-timeline-ci/validation.json) records the eight
frozen source hashes and recovered original-shell exit status; [log](runtime-allocation/audio-timeline-ci/full-suite.log)
preserves the completed run. Ruff 0.15.11 check/format pass for 1,073 files,
with canonical import identity. The [investigation](runtime-allocation/audio-timeline-ci/REPORT.md)
records the failed hosted head, native generator/mixer comparisons and the
explicit passthrough correction without weakening signal thresholds.

All 39 mixer tests pass with complete FFmpeg 7. The temporary native FFmpeg 6
build passes 37 scoped mixer tests, excluding two unavailable components; those
exclusions apply only to that local build. Hosted test selection is unchanged.
Final CI must be read for the exact corrected published head on the
[PR checks page](https://github.com/KyaniteLabs/kinocut/pull/586/checks).

## Earlier pre-merge review gate

Implementation `cfdf03a` resolves six inline-review findings after the earlier
green head. The required full suite passed **7,451 tests, 185 skipped, 8 warnings**
in 936.30 seconds, exit 0. [Result](runtime-allocation/pre-merge-review/validation.json)
records the command and eight frozen source hashes; [log](runtime-allocation/pre-merge-review/full-suite.log)
preserves the completed run. Ruff 0.15.11 check and format pass for the expanded
1,073-file scope, including the runtime audit; canonical/compatibility import
identity and touched-module/function limits pass.

The [review ledger](runtime-allocation/pre-merge-review/REPORT.md) records all
six findings, their corrections and actual regression evidence. The focused
audio/normalization/client-contract set passed 73 tests, the advertised-suffix
set passed eight, and audit-contract tests passed four. Primary FFprobe 6.1 also
passed five scoped timing/picture-tail/packet-cap cases, retaining FFmpeg 7.1.5
for fixture encoding, mixing and staged decode. Focused counts overlap the full
suite; skips do not validate optional inference backends.

Published head `5d3c4317c748b94fa4280259fdc759945f114fce` passed all thirteen CI
checks before this final review. That result is historical evidence, not CI for
`cfdf03a` or subsequent evidence commits. Inspect the exact published head on
the [PR checks page](https://github.com/KyaniteLabs/kinocut/pull/586/checks)
before merging; the PR records its final delivery status.

## Earlier grayscale and source-metadata gate

Implementation `1d35a9f9c1cf1c2df9d83da54ac090c3b68016a7` passed the required
full suite: **7,429 passed, 185 skipped, 8 warnings** in 938.46 seconds, exit 0.
[Result](runtime-allocation/iteration-3/grayscale-validation.json) records the
command, source hashes and scope; [log](runtime-allocation/iteration-3/grayscale-full-suite.log)
preserves the completed run. Exact CI Ruff 0.15.11 check/format pass for 1,070
files, along with canonical/compatibility import identity and architecture limits.
Final documentation claims/surface/privacy checks passed 57 tests in 7.05 seconds.
The Python 3.12 focused quality/cache/source/preflight gate passed 130 tests;
Python 3.14 with current dependencies passed its 90-test scoped gate.

The [cross-version comparison](runtime-allocation/iteration-3/grayscale-version-review.md)
reproduced the hosted assertion with primary FFprobe 6.1, then verified the repair
against FFprobe 7.1.5 across 48 fixtures/96 measurement sets without loosening
existing tolerances. Fixture creation and FFmpeg fallback used FFmpeg 7.1.5.
Earlier full-suite results below precede this repair and are historical checkpoints.
Published-head hosted results remain separate evidence on the PR checks page.

## Earlier Python 3.12 runtime checkpoint

The frozen runtime/test implementation passed **7,412 tests, 185 skipped, 8 warnings** in
966.23 seconds, exit 0:

```sh
UV_CACHE_DIR=/workspace/.cache/uv npm_config_cache=/workspace/.cache/npm .venv/bin/python -m pytest tests/ -x -q --tb=short
```

[Full log](runtime-allocation/iteration-3/full-suite.log) and
[structured result](runtime-allocation/iteration-3/validation.json) retain the
command and outcome. Runtime/test changes are banked through
`eb7b5ce42ae37bb948882c833360c2b0b2b743b2`; documentation follows separately.
The exact CI Ruff 0.15.11 check and format commands passed locally for 1,067
files, as did the canonical `kinocut.Client is mcp_video.Client` import check.
Local Python is 3.12 and FFmpeg is 7.1.5; the hosted PR safety lane uses Python
3.14. Optional skips are not validation of unavailable model backends.

Real MCP stdio initialization, listing all 201 tools and metadata-only
`search_tools` discovery passed without a model call. Source-verified Gemini CLI
configuration does not establish a paid Gemini/Claude end-to-end model session.
Live HTTP/site/provider observations and hash-verified package artifacts are
recorded in the external-report evidence; inspecting metadata is not installation.

## Source inventory

The [current allocation](runtime-allocation/audio-timeline-ci/allocation.json) classifies
625 runtime source files into deterministic code, operational LLM prose and
traditional/non-LLM ML integration. Percentages sum to 100%; they measure source
bytes, not execution time, cost, inference frequency or quality. Host skill prose
is reported separately. The [implementation checkpoint](runtime-allocation/iteration-3/IMPLEMENTATION.md)
records both retained changes and remaining measured-work opportunities.

## Hosted CI and release boundaries

The original head `0ff4fa51518b11aa2e36f74e0c5cc7287c5d5510` completed 13 checks:
12 passed, while Hosted PR checks failed at Lint and skipped Test. Pinned Ruff
reproduced the formatting failure; the current changes repair it. New-head CI
must be assessed against the exact pushed SHA rather than inherited results.
No workflow protections were disabled, and no issue or draft PR was closed.

The next head `581add657e9eeddd600241fc61f2dc4ff865dda6` passed hosted Lint and
12 other checks, but hosted Test failed after 930 seconds. Raw downloads were
blocked at the CONNECT proxy; generic exit-code annotations do not identify a
failing test. [The investigation](external-ai-audits/2026-09-30/HOSTED-TEST-INVESTIGATION.md)
records the diagnostic work and separates it from a verified runtime repair.

A separate Python 3.14.7 environment with frozen development dependencies also
passed the required full suite: **7,412 passed, 185 skipped, 8 warnings** in
954.12 seconds, exit 0. [Result](runtime-allocation/iteration-3/python314-validation.json)
and [log](runtime-allocation/iteration-3/python314-full-suite.log) record the
unchanged runtime/test tree and locally prepared CI diagnostics. This still uses
FFmpeg 7.1.5 and does not reproduce the hosted failure; hosted FFmpeg and unlocked
pip dependencies differ. Pinned lint/format now cover 1,068 files including the
new reporter, whose bounded annotations were separately exercised with real
pytest failures and malformed-input fixtures. The subsequent diagnostic head
identified a concrete hosted failure, recorded below.

The current-dependency Python 3.14.7 reproduction also passed **7,412 tests,
185 skipped, 8 warnings** in 957.04 seconds, exit 0: [result](runtime-allocation/iteration-3/python314-current-dependencies-validation.json)
and [log](runtime-allocation/iteration-3/python314-current-dependencies-full-suite.log).
It resolves the hosted dependency constraints without the lock, including MCP
1.30.0, NumPy 2.5.3 and pytest 9.1.1, but still uses local FFmpeg 7.1.5. This is
not an observed inventory of the hosted runner. Neither Python version nor current
dependency resolution alone has reproduced the failure.

At diagnostic head `00e07539f7ce7f83fb118b5c310bc6ccdc0770a9`,
[run 36754704771](https://github.com/KyaniteLabs/kinocut/actions/runs/36754704771)
passed Lint and the failure reporter completed successfully; the other twelve
checks passed, while hosted Test failed. Its accessible annotation identifies
`test_equivalent_ramps_share_limited_8bit_measurements[tv-gray]` in
`tests/test_quality_signalstats_bitdepth.py`: `YMIN=43.125` versus expected
`52.92941176470588 ± 1`. That run establishes accessible diagnosis, not
hosted-suite success. A scoped conversion repair was subsequently validated
locally, as recorded below.
The earlier `581add` run's failing case remains unknown.

Published PyPI/npm identity is 1.15.3, shim 1.6.14. This PR adds **Unreleased**
behavior without a version bump. Website identity and existing JSON-LD were
verified, but no deployment or complete browser/TLS review was performed.
GitHub latest release is 1.15.0; registry verification remains unavailable.
Merge #586 is separately authorized after its checks; release publication and
directory submissions have their own prerequisites.

## Grayscale repair: scope and hosted verification

Grayscale-only measurements now declare full range before conversion, including
TV-tagged grayscale, intentionally retaining the existing 8-bit grayscale policy.
Ordinary native YUV measurements remain unchanged. Shared source metadata/audio
stream checks reuse successful observations for unchanged sources and retry failed
probes; a first standalone visual measurement adds a metadata probe. Ambiguous
mixed grayscale/color video streams report unavailable. No universal latency
benefit or bisected upstream sole-cause claim is made.

The FFmpeg 6.1/7.1.5 matrix covers 48 fixtures and 96 measurement sets: native YUV
cross-version delta zero, maximum grayscale delta 0.6153, maximum absolute YMIN
error 0.13993, individual-measurement error zero, fallback error 0.38798 and
motion error 0.00892; sixteen static controls report zero motion. The final focused
quality/source/cache/preflight gate passed 130 tests. The
[matrix](runtime-allocation/iteration-3/grayscale-version-matrix.json) and
[review](runtime-allocation/iteration-3/grayscale-version-review.md) preserve
the scoped converter comparison.

The later full-suite gate passed as recorded above. Exact published-head hosted
checks must still be assessed separately; the converter comparison and earlier
checkpoints alone do not establish a successful hosted run. See the [hosted investigation](external-ai-audits/2026-09-30/HOSTED-TEST-INVESTIGATION.md)
for the diagnostic chronology and repair scope.

## Earlier checkpoints

At base `a820bd42205e43ca81eebc435e8529b2d0d42fcc`, the earlier integration gate
passed **7,320 tests, 183 skipped, 8 warnings** in 899.29 seconds.
[Recorded scope](github-backlog/2026-09-30/validation.json) and
[log](github-backlog/2026-09-30/full-suite.log) preserve that result.

The subsequently banked implementation `2ced642928ac93423fc6d92a260f7c4503919aaa`
passed **7,390 tests, 185 skipped, 8 warnings** in 1,003.32 seconds.
[Recorded result](runtime-allocation/pr-checkpoint/validation.json),
[log](runtime-allocation/pr-checkpoint/full-suite.log) and
[source inventory](runtime-allocation/pr-checkpoint/allocation.json) are historical
evidence. Focused and successive full-suite counts overlap and are not additive.

## UltraQA implementation checkpoint — October 1

Implementation `258cb0076f9ade77c41f6a528cf4c62d0745543a` retains the frozen 1,188-file source identity `5ae658513cdff7be42d2965572ed0c0a2da5233a5bb33c129844dbf384499966`. The [fourth sequential gate](ultraqa/2026-09-30/full-gate-attempt-4/result.json) passed **8,005 tests, 189 skipped, eight warnings** in 1,722.15 seconds, exit 0; the runner confirms source unchanged and 1,727.39 seconds wall time. Ruff check/format (1,110 files) and canonical import checks also passed. Earlier failed attempts and parallel preflight remain in the [gauntlet chronology](ULTRAQA_GAUNTLET.md); focused counts are not additive. At this pre-publication checkpoint, new exact-head hosted Windows/macOS and optional backend/model execution are separate pending evidence; hosted outcomes belong to the eventual PR exact-head checks. [Static source allocation](ultraqa/2026-09-30/final-runtime-allocation/allocation.json) is implementation-bound and does not measure runtime cost or latency.

## PR587 hosted repair checkpoint — pre-push

Initial `dddf3e1c88b9c3016b8fd9673fc589e9a5901a59` [hosted checks](ultraqa/2026-09-30/ci-attempt-1/result.json) finished 10 successful, 2 failed, 1 skipped out of 13; earlier partially observed snapshots remain distinct. Actual native6 proved zero-exit decoder errors; [final focused repair receipts](ultraqa/2026-09-30/ci-repair/result.json) preserve official binary provenance, ANSI-aware severity rejection, actual exit0 diagnostics and Windows test portability. Repair implementation `c28f7f30932212606eba14242f56bdbf20fff76e` passed [full attempt5](ultraqa/2026-09-30/full-gate-attempt-5/result.json): **8,013 passed,189 skipped,8 warnings** in 1,728.34 seconds, exit 0, unchanged frozen source; Ruff check/format and canonical import passed. [Updated static allocation](ultraqa/2026-09-30/final-runtime-allocation-5/allocation.json) is separately bound to this repair. Corrected hosted outcomes are **pending at this pre-push checkpoint**; later PR587 exact-head receipts establish those outcomes separately. No release version bump or deployment is implied.
