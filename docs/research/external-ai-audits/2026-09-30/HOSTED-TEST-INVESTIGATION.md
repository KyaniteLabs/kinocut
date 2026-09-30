# Hosted test failure and accessible diagnostics

The exact PR head `581add657e9eeddd600241fc61f2dc4ff865dda6` completed all
checks on September 30, 2026. Twelve passed, including the three-platform staged
runtime, FFmpeg smoke and clean-wheel onboarding. The
[hosted safety run](https://github.com/KyaniteLabs/kinocut/actions/runs/36749871139)
passed Lint but failed Test after 930 seconds (17:14:31–17:30:01 UTC).
That job uses Python 3.14 and the runner's FFmpeg build; the passing local
7,412-test gate used Python 3.12 and FFmpeg 7.1.5.

## Evidence boundary

The check annotation contains only `Process completed with exit code 1`.
There is no test failure text in the accessible summary or artifacts. Both run
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
failure is fixed.
