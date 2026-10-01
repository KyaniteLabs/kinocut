# KinoCut debt closure and delivery evidence

This follow-up starts from merged master `3db9ba9f9cad590f4c018b76091ee3c27e7106fd`
on branch `codex/kinocut-debt-closure`. It covers the resource, architecture,
latency, acceptance and operational findings in the current status review.
Published 1.15.3 artifacts remain distinct from these Unreleased source changes.

## Repository repairs

| Finding | Implemented result | Acceptance |
| --- | --- | --- |
| Captured subprocess output | Shared bounded draining rejects oversized stdout/stderr instead of retaining arbitrary output or returning truncated JSON. Explicit sinks check their byte budget before writes. | Actual flood, exact-bound, binary, partial-sink and invalid-sink fixtures; final full gate passed. |
| Windows process descendants | Children start suspended, enter a kill-on-close Job Object, then resume. POSIX uses owned sessions; both stop surviving descendants when the leader exits. | Actual Linux grandchild heartbeat/timeout controls plus Windows ABI controls; native hosted gate pending. |
| Timeline/visual metadata disk use | FFprobe writes through an anonymous owned stdout sink with a producer byte ceiling. Packet/line/deadline limits remain. | Real flooding producer verifies disk bytes never exceed the selected budget. |
| Publication failures and hostile paths | Missing ancestry creation is anchored and no-follow on supported POSIX systems. Directory and inode identities are checked after replacement. Observed post-publication substitutions and media/receipt split failures return explicit partial-publication errors. | Safe path, directory, inode and sidecar failure fixtures; exclusive writer ownership remains required. |
| Render-worker layer coupling | Detached jobs invoke the existing workflow engine directly, preserving errors, cancellation, resume and lineage without importing MCP handlers. | Transport-blocked import and real missing-source error controls. |
| Sound policy duplication | All thirteen centralization TODOs resolved; public aliases preserve original values. A static constant facade preserves exports while keeping the package initializer below its size ceiling. | Centralization/export and optional-import controls. |
| Test latency | PR safety uses at most two pytest workers with file grouping, retaining the same test selection, assertions and JUnit/annotation behavior. | Source-bound representative serial/two/four-worker comparison below. |
| Repeated ASR WAV decoding | Same-job validation returns the already-decoded PCM to ASR; no cross-job cache or staged-output decode guard is removed. | Exact PCM bytes/hash/sample count and ingress error controls. |
| Motion review acceptance | A separate Python Client operation records source/report-bound complete human viewing and explicit dispositions for all flagged intervals/cuts. | Calm, steady, lurch, high-rate, freeze and cut controls; partial/invalid evidence must reject. |
| Semantic vision availability | Explicit model/key configuration enables one fixed-origin paid keyframe request in a bounded worker; absent configuration remains unavailable. | Fake HTTP and actual local child failure/deadline/cleanup controls; live provider accuracy unverified. |
| Fabricated voice loudness | Voice batches report unmeasured loudness explicitly; callers meter the assembled master separately. Perceptual evidence rejects malformed scores and preserves provider drift. | Measured/unmeasured receipt migration and adversarial provider controls. |
| Font download/cache correctness | Isolated allowlisted downloader has an elapsed deadline and byte caps. Parent-owned staged writes and structural SFNT/TTC validation prevent corrupt partial cache success. Windows unresolved families reject before FFmpeg. | Real truncated fonts, bounded malformed containers, hanging/flooding/trickle workers and actual Linux text renders; native hosted font gate pending. |
| AI scene extraction bounds | A hard frame ceiling plus one overflow sentinel prevents inconsistent duration metadata from silently creating or accepting excess frames. Both thumbnail dimensions are bounded; malformed/nonfinite/overflowing durations reject before the producer. | Real short-clip overflow, exact-bound success, extreme-aspect and normal-aspect controls; ordinary processing fallback remains. |
| Detached worker hard termination | A worker-scoped POSIX guardian retains the lease and kills its own native group on worker liveness-pipe EOF. The controller never signals recorded PIDs; validated live workers consume stop intent themselves. Unwatched legacy workers remain pending. | Real native FFmpeg before/after hard-kill and lease-release proofs; 80 integrated and 48 independent focused tests passed. Normal commands are reaped; abnormal zombies require host PID1 reaping. |
| Generic POSIX process identity after completion | Nonreaping observation retains the leader until group cleanup and sole reap. Unsupported POSIX uses a live supervisor, bounded native-status pipe and self-stop on parent-only EOF. Detected external reaping refuses numeric signals; sole-reaper ownership is required. | Safe old-signal interception, native/forced-fallback status/FD/stream/descendant controls; 92 independent tests passed at the earlier integration checkpoint; final cleanup selection passed 81 with three native-Windows skips. |
| Raw launch failures and drainer errors | Missing/unexecutable launches return redacted typed processing errors. Cleanup error channels are bounded; original cap/callback errors survive verified cleanup. Windows unassigned suspended startup still uses its stable handle. | Actual missing/unexecutable native and forced-fallback fixtures, descriptor census and startup-handle control. |
| Cancellation shutdown transition | A lease becoming free during initial checks triggers a fresh quiescence and lease check before a terminal result. Live/reacquired cases remain unconfirmed. | Actual before failure in one of 30 repeats; after 30/30 confirmed. Three deterministic zero-signal transition controls. |

## Measured performance scope

On one immutable baseline, the same 257 representative tests had identical case
identities and outcomes (256 passed, one skipped): serial **204.197s**, two workers
**112.373s**, four workers **76.385s**. The selected two-worker cap reduced this
run's wall time by **45.0%**, reserving capacity for native codec threads. These
measurements do not predict every full-suite or runner's performance.

Three fresh-process import trials measured the detached render worker median
**0.8474s → 0.4520s** after removing transport imports. Rendering and model
initialization are outside that measurement. A pre-review post-guardian three-trial
check measured a **0.4005s** median with no MCP or server-app import; variation
between checkpoints is not a rendering-throughput comparison. At maximum legal PCM input, avoiding
the second WAV decode measured **3.832ms → 2.176ms** with identical PCM; peak RSS
was essentially unchanged. This is a frontend saving, not an ASR inference claim.

Full staged audio decoding remains an intentional corruption/timing guard.
Removing it solely to reduce CPU would weaken the supported contract.

[Retained measurement and review receipts](debt-closure-evidence/README.md)
preserve the case identity, frontend measurements, pixel-equivalence controls and
legacy serialization comparisons rather than relying on prose alone.

## Independent review and full validation

Six parallel tracks implemented and reviewed the repairs. Cross-owner reviews
reproduced and repaired further truncated-font, trickle-timeout, post-rename
directory, incomplete-motion and malformed-provider failures. Focused selections
overlap and must not be added together. The initial frozen parallel preflight
found 17 failures (8,198 passed, 189 skipped). Those exposed a legacy measured
receipt serialization/hash regression and outdated test integration seams. The
repairs preserve the original numeric receipt fixtures and hashes. Independent
review compared the old and new serialization projections, including nested
canonical hashes; its 443-test selection passed. Scene extraction then passed
108 focused tests with nine optional-environment skips. Independent scene review
also verified identical decoded thumbnail pixels for ordinary square, landscape
and portrait controls. The first passing checkpoint wheel/source archive pass content checks, and all **644 shipped
Python files** byte-match frozen source identity
`fe57832a86cea67326405da24f390a8df701c9c1e24ca87776a8e4351e34697d`. Pyright reports zero
errors and warnings; configured Ruff/format and import compatibility pass.
After the live documentation updates, the architecture/public-surface/claim
selection passed **64 tests** in 13.20s.

The first serial gate was stopped after the census found that hard termination
could leave media processing alive. Its source identity remained unchanged. It
finished with exit one (6,815 passed, 166 skipped and one MCP stdio shutdown
exception), so it is not a passing full gate. The named routing case, a 72-test
routing selection and three separate mono/stereo transport repetitions passed
afterward. The captured failure is consistent with interruption/SDK shutdown;
its exact causation is not proven.

The guardian and self-stop repair pass focused integration and independent
review. The pre-review required serial command passed **8,257 tests, 189 skips and
eight warnings in 1,723.75s**, exit zero. Its 1,211 selected runtime, test, script
and workflow files retained frozen identity
`fe57832a86cea67326405da24f390a8df701c9c1e24ca87776a8e4351e34697d`.
The wrapper independently observed exit zero in 1,726.71s. The completed-run
process census initially found two task-owned fake-FFmpeg producers from the
failed, older parallel preflight. Exact argv/start-time checks and PID-pinned
cleanup stopped those fixtures; the subsequent census found no matching
executing native media or guardian processes.
Normal and abnormal reaping limits above remain unchanged.

PR [#588](https://github.com/KyaniteLabs/kinocut/pull/588) banks implementation
`2db0b90`, documentation `f55a816`, and post-review repairs `bedcaa7`. On that exact head, hosted Linux passed
**8,232 tests, 50 skips and eight warnings in 546.58s** using two workers. Native
macOS passed the guardian/controller controls but two text renders failed because
the selected Homebrew FFmpeg lacked `drawtext`; three drainer cleanup warnings
also exposed the reaped-leader gap above. Windows real default/explicit text
renders passed; two fixture assumptions about CRLF and escaped filesystem paths
failed. Both fixtures are repaired without weakening render/decode assertions.
The official Homebrew `ffmpeg-full` formula was verified to provide freetype and
harfbuzz; CI now selects that keg and explicitly checks `drawtext` before use.

The code reviewer requested typed spawn failures; that request is implemented.
The independent review additionally reproduced the generic lifetime and
cancellation transition failures above. Runtime/test/workflow files are now
frozen at 1,213-file identity
`4e06562528aec90609c8a24a3976888fb99c1da833700094541544fb1ce8a831`
for the new required serial gate. A post-review attempt stopped after 2,142
passes and 143 skips because the old stdin fixture expected raw `OSError`. Its
four `DEVNULL` assertions remain; expectations now require the reviewed typed
error. The 54-test helper/process selection passed. The next attempt found
that only the core toolchain resolver checked `drawtext`; the optional lane
still used the prior duplicate resolver. Both now use the same bounded probe,
with missing-filter rejection controls on both. All 267 MCPB, distribution and
architecture controls passed before this new freeze. Prior passing results remain separate checkpoints. The final required serial
gate passed **8,281 tests, 189 skips and eight warnings in 1,927.42s**, exit
zero. The wrapper observed exit zero in 1,932.36s; all 1,213 selected files
retained the frozen identity above. Post-run census found no matching executing
native media or guardian processes. Rebuilt wheel/source archive checks pass,
with all **645 shipped Python files** matching this frozen source. Configured
Ruff check/format covers 1,135 files; Pyright reports zero errors and warnings.
New exact-head CI and resolution of the review thread remain before merge. The separate security-review
bot reports its payer's usage limit; it is not a completed security review.

## Product scope and external prerequisites

[Operational evidence and issue dispositions](debt-closure-operations.md) records
all eleven operational/platform issues, isolated published-runtime execution and
current distribution checks. [Feature acceptance](debt-closure-feature-acceptance.md)
documents review receipts, provider execution, migration and untested quality.

Full-episode acceptance still requires representative Apple-Silicon benchmark
and authorized episode/listening receipts. Paid-provider credentials, a desktop
user's installation acceptance, directory-review approval and private operator
readback are also unprovided. Native runtime CI has its separately recorded scope.
Site requests still receive proxy HTTP403 with TLS verification enabled. They do
not prove a current origin TLS failure or success. Forgejo remains excluded at
the user's explicit request.

Fresh GitHub inspection finds releases 1.15.1/1.15.2/1.15.3 as drafts; latest
published GitHub release remains 1.15.0. The initially unbound 1.15.3 draft has now
been repaired: tag `v1.15.3` and release target bind the independently verified
original source `a820bd42205e43ca81eebc435e8529b2d0d42fcc`, and the existing
checksum-verified notes are restored as its body. It remains a draft; publication
was not triggered. These new source repairs remain Unreleased. The original wheel
and shim publisher attestations verified offline with the installed trust
snapshot; online trust freshness and current registry alignment remain unverified.

No unavailable hardware, provider, external approval or human viewing is marked
as tested. Open issues close only when their actual criteria have evidence or an
explicit scope decision, never merely because a checklist exists.
