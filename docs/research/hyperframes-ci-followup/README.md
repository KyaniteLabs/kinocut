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
Large changed-file lists are checked under the actual Bash `pipefail` semantics;
here-strings prevent an early-success grep from turning into a false negative
when its former printf producer receives SIGPIPE.

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
[The final full serial receipt](full-serial.json) records **8,348 passed,
189 skipped and eight warnings in 1,858.59 seconds**, exit zero, on unchanged
1,216-file source identity
`604be219d8f563d9a4dec5ad7ce0ad514dd8d183ed825976f8b0707b55a80631`.
[The current independent review](independent-review.json) binds both workflows,
shared policy modules, checker and tests; the two CLI passes and opt-out rejection
were repeated after the policy repair. [Build verification](build-source-binding.json)
matches all 645 shipped Python files against the frozen source and verifies the
installed wheel outside the checkout, with existing dependencies explicitly shared.

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
