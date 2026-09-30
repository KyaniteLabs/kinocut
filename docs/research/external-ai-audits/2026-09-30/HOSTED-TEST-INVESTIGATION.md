# Hosted test failure and accessible diagnostics

The exact PR head `581add657e9eeddd600241fc61f2dc4ff865dda6` completed all
checks on September 30, 2026. Twelve passed, including the three-platform staged
runtime, FFmpeg smoke and clean-wheel onboarding. The
[hosted safety run](https://github.com/KyaniteLabs/kinocut/actions/runs/36749871139)
passed Lint but failed Test after 930 seconds (17:14:31–17:30:01 UTC).
That job uses Python 3.14 and the runner's FFmpeg build; the passing local
7,412-test gate used Python 3.12 and FFmpeg 7.1.5.

## Evidence boundary

For head `581add657e9eeddd600241fc61f2dc4ff865dda6`, the check annotation
contained only `Process completed with exit code 1`; that run's accessible
summary and artifacts did not identify a failing case. Both run
and job log requests redirect to signed storage destinations, and the environment
proxy rejects CONNECT before those origins respond. This is log transport denial,
not evidence about which test failed. Signed URLs and credentials were not copied
to documentation. Anonymous job HTML does not expose the failing test text.

The reusable environment draft adds the two observed log hosts while preserving
the existing package-manager preset and domain entries. Draft persistence does
not establish runtime application or successful downloads. In parallel, a separate
Python 3.14 environment uses frozen development dependencies for reproduction;
the existing Python 3.12 environment, lockfile and package pins are preserved.

## Diagnostic improvement

The hosted test command now writes a JUnit report in runner temporary storage.
Its selection and exit status remain intact. A failure-only step runs
`scripts/annotate-pytest-failures.py` so the accessible check API can show failing
case identities, assertion summaries and bounded traceback detail.

The standalone stdlib helper accepts reports up to 8 MiB from a regular, nonsymlink
file, reading one additional byte to detect oversized input. It
requires UTF-8 XML, rejects DTD/entity declarations, and emits at most ten failure
annotations. It caps messages and escapes percent signs, carriage returns and
newlines as workflow-command data. File/path annotation properties are not
derived from report content. Missing, invalid or oversized reports yield diagnostic
warnings; the prior pytest failure still determines job failure.

No token permission, secret, dependency, runner, test assertion or protection was
expanded or disabled. Future helper edits trigger the existing code lane and its
pinned lint checks. Quoted shell `RUNNER_TEMP` paths avoid unsupported job-level
runner expressions.

## Validation

Pinned Ruff 0.15.11 check and format pass for the expanded 1,068-file scope.
YAML structure, shell fragments, classifier positive/negative controls and diff
checks pass. Manual fixtures cover absent and all-pass reports, real pytest
assertion failure with exit 1, escaping, annotation limits, oversized reports,
DTD, UTF-16 and symlinks. The diagnostic helper exits normally without replacing
the original pytest status. `actionlint` was unavailable and is not claimed run.

The frozen-dependency Python 3.14.7 reproduction passed **7,412 tests, 185 skipped,
8 warnings** in 954.12 seconds, exit 0. [Result](../../runtime-allocation/iteration-3/python314-validation.json)
and [log](../../runtime-allocation/iteration-3/python314-full-suite.log) preserve
that evidence. It used local FFmpeg 7.1.5, so Python version alone has not
reproduced the hosted failure. Hosted FFmpeg and unlocked pip dependencies remain
different. Subsequent exact-head annotations must identify the actual failing
case; this diagnostic change alone does not establish that the original hosted
failure is fixed. The subsequent diagnostic run below supplied that case.

The subsequent current-dependency Python 3.14.7 run passed **7,412 tests,
185 skipped, 8 warnings** in 957.04 seconds. [Result](../../runtime-allocation/iteration-3/python314-current-dependencies-validation.json)
records the locally resolved versions, including MCP 1.30.0, NumPy 2.5.3,
scikit-learn 1.9.1 and pytest 9.1.1. This does not establish the hosted inventory;
the hosted FFmpeg build and operating environment remain different.

## Accessible failure on the diagnostic head

At exact head `00e07539f7ce7f83fb118b5c310bc6ccdc0770a9`,
[hosted safety run 36754704771](https://github.com/KyaniteLabs/kinocut/actions/runs/36754704771)
passed Lint but failed Test. The failure-only reporter completed successfully and
exposed the assertion through check annotations:

```text
tests/test_quality_signalstats_bitdepth.py
test_equivalent_ramps_share_limited_8bit_measurements[tv-gray]
YMIN: observed 43.125; expected 52.92941176470588 ± 1
```

The other twelve checks passed. Reporter success establishes accessible failure
diagnostics, not a passing test suite. This case identifies a limited-range gray
measurement discrepancy on that hosted run; it does not identify the failing
case from the earlier `581add` run, establish the root cause or verify a repair.
A locally validated conversion repair is described below. A subsequent
exact-head hosted result remains required before claiming hosted resolution.

## Locally validated grayscale conversion repair

Grayscale-only measurement now declares `setparams=range=full` before conversion.
This intentionally treats grayscale samples as full-range even with a TV/limited
range tag, matching the existing 8-bit grayscale policy and removing an implicit
FFmpeg-version-dependent conversion choice. Ordinary native YUV measurement is
unchanged. The official FFmpeg 6.1 reproduction and related later swscale repairs
provide context; no upstream commit was bisected as the sole cause.

The shared measurement path caches source metadata and audio-stream checks for
unchanged source identity; failed probes retry. A first standalone visual
measurement now adds a metadata probe. Mixed grayscale/color video streams are
ambiguous and report unavailable rather than selecting an invented range policy.
No universal latency improvement is claimed.

Local comparison covers **48 fixtures, 96 measurement sets** across FFmpeg 6.1
and 7.1.5. Native YUV cross-version delta is zero. Maximum grayscale delta across
range tags is 0.6153 (below 1), and maximum absolute YMIN error is 0.13993
(below 0.2). Individual-measurement comparison error is zero; fallback error is
0.38798 (below 0.6), motion error is 0.00892, and all sixteen static controls
report zero motion. The final focused quality/source/cache/preflight gate passed **130 tests**.

The [matrix](../../runtime-allocation/iteration-3/grayscale-version-matrix.json)
and [review](../../runtime-allocation/iteration-3/grayscale-version-review.md)
preserve the comparison. These fixtures validate the scoped measurement
repair locally. The final full-suite gate passed **7,429 tests, 185 skipped,
8 warnings** in 938.46 seconds, exit 0, with source banked in `1d35a9f`.
[Result](../../runtime-allocation/iteration-3/grayscale-validation.json) and
[log](../../runtime-allocation/iteration-3/grayscale-full-suite.log) preserve
that outcome. Published-head hosted results remain separate evidence; neither
a local pass nor the earlier successful suites imply hosted resolution.

## Avoidable runner setup

The diagnostic head `00e07539f7ce7f83fb118b5c310bc6ccdc0770a9` spent 14 minutes
55 seconds in the unconditional FFmpeg install step before reaching tests. The
existing integration workflow checks for installed FFmpeg first. Hosted safety
now follows that pattern for both FFmpeg and ffprobe, retaining version checks
and the existing apt recipe when either binary is missing. A ten-minute step
timeout bounds dependency installation. Controlled shell fixtures verify the
skip, missing-tool installation and retained installer-error paths. This setup
change is separate from diagnosing the earlier test failure.

## Subsequent hosted result and pre-merge review

Published head `5d3c4317c748b94fa4280259fdc759945f114fce` subsequently passed
all thirteen exact-head checks. Hosted safety [run 36765393126](https://github.com/KyaniteLabs/kinocut/actions/runs/36765393126)
passed Lint and Test; Test completed in 15 minutes 20 seconds and the failure
reporter was correctly skipped. FFmpeg setup completed in 84 seconds on this
run. Runner conditions vary, so comparison with the earlier 14-minute-55-second
setup is an observation rather than a universal speed guarantee.

Final inline review found six actionable audit/audio issues despite those green
checks. Their later [corrections and evidence](../../runtime-allocation/pre-merge-review/REPORT.md)
require their own full local gate and fresh published-head CI. The earlier
green head does not validate the later changes; inspect the exact head on
[PR #586](https://github.com/KyaniteLabs/kinocut/pull/586) for its final delivery
and check status.
