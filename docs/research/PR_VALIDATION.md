# PR validation and publication scope

[PR #586](https://github.com/KyaniteLabs/kinocut/pull/586) reviews branch
`codex/kinocut-reliability-and-backlog` against `master`. The user authorized
commits, branch pushes and PR creation. Draft contributor PRs were reviewed and
adapted, not merged. See the [backlog dispositions](github-backlog/2026-09-30/REPORT.md),
[external-report action ledger](external-ai-audits/2026-09-30/REPORT.md) and
[Unreleased changelog](../../CHANGELOG.md).

## Final grayscale and source-metadata gate

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

The [current allocation](runtime-allocation/iteration-3/allocation.json) classifies
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
No release, merge, directory submission or external message is implied.

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
