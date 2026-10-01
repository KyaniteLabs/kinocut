# Hyperframes integration gate evidence

The previous GitHub job installed Hyperframes but omitted the explicit integration
opt-in. Its pytest command returned zero with both selected tests skipped.
This follow-up enables the tests and checks their actual JUnit cases before
accepting the job. The CLI is pinned to the 0.8.104 version observed in the
completed master run, with package lifecycle scripts disabled. Checker-only
changes are classified as code changes by both master and hosted PR workflows,
so future gate repairs execute their guard regressions. CI-workflow-only changes
also execute hosted PR tests. The result guard imports its byte ceiling from
`kinocut/limits.py` and its execution minimum from `kinocut/validation.py`;
semantic policy-change fixtures verify that central changes affect the guard.
Classifiers read NUL-separated Git records in their owning shell, with rename
detection disabled. This preserves Unicode/control characters and removed paths
when runtime files move into docs. Entire workflow and CI-script directories
trigger guard regressions. Git errors stop before publishing success outputs;
owned path-list files are removed on success/failure, filename logs use escaped
representations, and classification has a one-minute deadline. Actual isolated
Git fixtures cover large lists without the former early-closing grep pipeline.

[Independent review](independent-review.json) binds the workflow, result checker
and live test source by SHA256. It records two executed CLI/project-validation
passes, a skipped-only negative control, rejection by the checker and shell-step
termination. The checker also has actual pytest-generated pass, skip, failure
and empty-report regression fixtures; reports have a 64 KiB read ceiling and
must contain at least two consistent cases with no skips, failures or errors.

The live project test requires no issues or warnings, so the validator's caught
lint-launch warning cannot pass this integration fixture. These tests establish
CLI resolution and validation of a small static HTML project. They do not render
frames, exercise a browser or call paid providers.

[The initial full serial checkpoint](initial-full-serial.json) records **8,330 passed,
189 skipped and eight warnings in 2,271.43 seconds**, exit zero, on unchanged
1,215-file source identity
`202de724d5bed9457f5936473ed47d31ad0a43103ce14ff824953f5a617002d9`.
Thirty-three focused guard/classifier cases and the separate two live CLI cases
passed on that initial source, before the shared-policy and hosted PR repairs.
Those review repairs pass 51 focused policy/guard/classifier cases.
Two review-driven interrupted checkpoints and the omitted writable-cache
failure are retained as superseded evidence, not counted as full passes.
[The policy-stage full serial checkpoint](policy-full-serial.json) records **8,348 passed,
189 skipped and eight warnings in 1,858.59 seconds**, exit zero, on unchanged
1,216-file source identity
`604be219d8f563d9a4dec5ad7ce0ad514dd8d183ed825976f8b0707b55a80631`.
That result predates the NUL/rename/control-family and provisioning repairs.
Its [independent review](policy-independent-review.json),
[build](policy-build-source-binding.json) and
[29 successful hosted checks](policy-hosted-ci.json) remain historical evidence.

The final control-input source passes **148 focused tests**, including actual Git
commits/workflow Bash and all seven Linux setup blocks in safe isolated tool paths.
Nested sound-package changes execute both real classifiers and require testing
and Docker build gates. These behavioral cases replace two obsolete regex-only
checks that caused the previous full run to stop after 6,096 passes and 161 skips.
[Independent security review](independent-security-review.json) binds 96 separate
Git/shell controls plus eight XML controls, including invalid references, partial
Git failures, temporary-file cleanup, unusual names and both rename directions.
This is an independent review; the separate automated security bot is quota-blocked.
[Current independent CLI/workflow review](independent-review.json) verifies all
1,218 frozen file hashes. It reuses the two actual CLI passes and opt-out rejection
because every runtime input to those controls is byte-identical.

[Build verification](build-source-binding.json) matches all 645 wheel runtime
Python files and all 652 source-archive Python files, including seven intentional
packaging scripts, against the frozen source. The source archive includes the
updated changelog. Installed wheel imports pass outside the checkout with existing
dependencies explicitly shared. [Provisioning evidence](ffmpeg-provisioning.json)
records both-tool detection, omitted recommended packages and 45-minute phase
ceilings; Hyperframes' overall 30-minute bound remains tighter. The observed
87-package/62.8 MB/173 MB lean installation versus 100 packages plus four upgrades/
105 MB/227 MB default installation is a cross-run footprint comparison, not a
controlled elapsed-time speedup. Existing static version-matrix coverage and
native validation assertions remain. The main check keeps its legacy name while
its runtime, comment and skip message identify Python 3.14.

[The final full serial gate](full-serial.json) passes **8,440 tests, 189 skips and
eight guardrail-fixture warnings in 1,685.55 seconds**, exit zero, on unchanged
1,218-file source identity
`4358148ccae9cdc91a64991ac7fd027a4dbc3119d93a066a40eff572ab3f5bbd`.
Earlier passing checkpoints, the failed obsolete-regex checkpoint and the two
interrupted source-stable final-stage attempts remain separate evidence.
Superseded attempts retain their actual exit codes, source hashes and log digests.

[Initial hosted evidence](initial-hosted-ci.json) records all 24 initial-head
checks passing, including two executed Hyperframes cases and guard acceptance.
It predates both review repairs. [The initial independent receipt](initial-independent-review.json)
also remains a historical checkpoint. [The manifest](manifest.json) binds all
curated payloads. Exact-head hosted
results and merge metadata belong to the
[associated follow-up PR](https://github.com/KyaniteLabs/kinocut/pull/589)
and its Actions receipts, rather than being inferred from local tests.

The prior merged delivery, historical checkpoints, external issue requirements
and untested areas remain in [the debt ledger](../DEBT_CLOSURE.md).
