# Debt-closure verification receipts

These retained receipts support [the debt-closure ledger](../DEBT_CLOSURE.md).
They distinguish immutable baseline measurements, repaired-source controls, an
initial failed preflight and the final development build. Overlapping focused
test totals are not additive. Local cache paths in commands identify the original
working location; the accompanying JSON is retained here for inspection.

- `ci-worker-comparison.json` uses the same baseline, case identities and test
  outcomes in serial, two-worker and four-worker executions.
- `pcm-reference.json` and `pcm-reuse.json` isolate WAV frontend work; they do not
  measure speech recognition or model quality.
- `render-import-before.json` and `render-import-after.json` measure fresh process
  imports, not rendering throughput. `render-import-final.json` repeats the
  measurement after the guardian repair and separately records static platform
  review; Windows/macOS native execution is not claimed by that local receipt.
- `receipt-serialization-review.json` compares legacy Python/JSON projections and
  nested canonical hashes after the measured-status compatibility repair.
- `scene-before.json` and `scene-after.json` record real extraction resource
  reproductions. `scene-independent-pixels.json` verifies common geometry and
  decoded pixels independently of the implementation owner.
- `initial-parallel-preflight.json` is the failed checkpoint before compatibility
  and integration repairs. It is not the final test result.
- `native-worker-kill-before.json` reproduces real FFmpeg executing after an old
  controller claimed shutdown. `native-worker-kill-after.json` verifies hard
  worker death stops the native group and releases the inherited lease.
- `independent-native-render-stops.json` exercises shipped detached jobs and real
  FFmpeg through both cancel and terminate APIs, with exact source hashes.
  `guardian-live-census.json` records no matching executing fixture processes.
  Normal command reaping is verified separately; abnormal zombies still depend
  on host PID1 reaping and these receipts do not claim otherwise.
- `build-source-binding.json` binds the local wheel's shipped Python bytes to the
  frozen source identity in both the wheel and source archive. The package version remains 1.15.3 during development;
  this wheel was not published over the existing release.
- `release-draft-alignment.json` records readback of the existing release draft
  and original-source tag repair. Its `publication_triggered=false` distinguishes
  metadata repair from a release event.

- `full-serial.json` records the completed required serial gate with its actual
  exit status and unchanged selected-source identity. `post-full-live-census.json`
  checks for executing media/guardian fixtures after that completed gate.
- `static-checks.json` records configured lint/format/type scopes, canonical
  imports and required core readiness, with optional capabilities distinguished.

`manifest.json` records hashes of the retained verification files. Hosted CI,
review and merge results are added only after those actions finish.
Paid-provider accuracy, desktop installation, representative episode listening
and private operator state remain outside these local receipts.

Post-review controls retain the safely intercepted reaped-leader signal and
independent retained-identity/native-status proof. Stop-transition receipts record
one actual pre-fix cancellation race and 30 confirmed post-fix repetitions.
`pre-review-passing-serial.json` and `pre-review-build-source-binding.json` remain
explicit earlier passing checkpoints, not evidence for subsequent repairs.

`post-review-failed-serial.json` records the stale raw-spawn expectation and
its correction without weakening stdin isolation. `retained-leader-review-manifest.json`
records the pre-stdio independent cleanup selection and source hashes; referenced
large logs remain in the original local cache.

`post-review-resolver-failed-serial.json` preserves the asymmetric CI resolver
failure, its repair and the complete 267-test MCPB/distribution/architecture gate.

`portable-stdio-independent.json` retains the actual pre-fix fallback failures,
all-selector/reader results, native measurements and exact process/test hashes.
`pre-stdio-full-serial.json` and `pre-stdio-build-source-binding.json` identify the
passing Linux checkpoint before that cross-platform repair; they do not certify
its successor. Native `8328a26` failures remain explicit in the ledger. `full-serial.json`, `post-full-live-census.json`, the build and current static checks identify the passing portable/readiness successor. `pre-stdio-static-checks.json` preserves the prior static/documentation checkpoint.

`portable-stdio-doc-privacy-failed-serial.json` records the rejected hosted-receipt home path and failed gate, followed by redaction and the four passing privacy controls. The raw hosted log checksum and failure counts remain unchanged.

`portable-timeout-fixture-failed-serial.json` preserves the subsequent scheduler-dependent marker failure and the explicit readiness repair. Its startup allowance does not alter the0.1-second reader execution deadline or cleanup assertions.
