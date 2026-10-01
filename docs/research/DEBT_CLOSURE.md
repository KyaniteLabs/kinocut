# KinoCut debt closure and delivery evidence

This follow-up starts from merged master `3db9ba9f9cad590f4c018b76091ee3c27e7106fd`
on branch `codex/kinocut-debt-closure`. It covers the resource, architecture,
latency, acceptance and operational findings in the current status review.
Published 1.15.3 artifacts remain distinct from these Unreleased source changes.

## Repository repairs

| Finding | Implemented result | Acceptance |
| --- | --- | --- |
| Captured subprocess output | Shared bounded draining rejects oversized stdout/stderr instead of retaining arbitrary output or returning truncated JSON. Explicit sinks check their byte budget before writes. | Actual flood, exact-bound, binary, partial-sink and invalid-sink fixtures; passing serial checkpoints are recorded below. |
| Windows process descendants | Children start suspended, enter a kill-on-close Job Object, then resume. POSIX uses owned sessions; both stop surviving descendants when the leader exits. | Actual Linux grandchild heartbeat/timeout controls plus Windows ABI controls; native hosted regression gate passes below. |
| Timeline/visual metadata disk use | FFprobe writes through an anonymous owned stdout sink with a producer byte ceiling. Packet/line/deadline limits remain. | Real flooding producer verifies disk bytes never exceed the selected budget. |
| Publication failures and hostile paths | Missing ancestry creation is anchored and no-follow on supported POSIX systems. Directory and inode identities are checked after replacement. Observed post-publication substitutions and media/receipt split failures return explicit partial-publication errors. | Safe path, directory, inode and sidecar failure fixtures; exclusive writer ownership remains required. |
| Render-worker layer coupling | Detached jobs invoke the existing workflow engine directly, preserving errors, cancellation, resume and lineage without importing MCP handlers. | Transport-blocked import and real missing-source error controls. |
| Sound policy duplication | All thirteen centralization TODOs resolved; public aliases preserve original values. A static constant facade preserves exports while keeping the package initializer below its size ceiling. | Centralization/export and optional-import controls. |
| Test latency | PR safety uses at most two pytest workers with file grouping, retaining the same test selection, assertions and JUnit/annotation behavior. | Source-bound representative serial/two/four-worker comparison below. |
| Repeated ASR WAV decoding | Same-job validation returns the already-decoded PCM to ASR; no cross-job cache or staged-output decode guard is removed. | Exact PCM bytes/hash/sample count and ingress error controls. |
| Motion review acceptance | A separate Python Client operation records source/report-bound complete human viewing and explicit dispositions for all flagged intervals/cuts. | Calm, steady, lurch, high-rate, freeze and cut controls; partial/invalid evidence must reject. |
| Semantic vision availability | Explicit model/key configuration enables one fixed-origin paid keyframe request in a bounded worker; absent configuration remains unavailable. | Fake HTTP and actual local child failure/deadline/cleanup controls; live provider accuracy unverified. |
| Fabricated voice loudness | Voice batches report unmeasured loudness explicitly; callers meter the assembled master separately. Perceptual evidence rejects malformed scores and preserves provider drift. | Measured/unmeasured receipt migration and adversarial provider controls. |
| Font download/cache correctness | Isolated allowlisted downloader has an elapsed deadline and byte caps. Parent-owned staged writes and structural SFNT/TTC validation prevent corrupt partial cache success. Windows unresolved families reject before FFmpeg. | Real truncated fonts, bounded malformed containers, hanging/flooding/trickle workers and actual Linux text renders; native hosted font regression gate passes below. |
| AI scene extraction bounds | A hard frame ceiling plus one overflow sentinel prevents inconsistent duration metadata from silently creating or accepting excess frames. Both thumbnail dimensions are bounded; malformed/nonfinite/overflowing durations reject before the producer. | Real short-clip overflow, exact-bound success, extreme-aspect and normal-aspect controls; ordinary processing fallback remains. |
| Detached worker hard termination | A worker-scoped POSIX guardian retains the lease and kills its own native group on worker liveness-pipe EOF. The controller never signals recorded PIDs; validated live workers consume stop intent themselves. Unwatched legacy workers remain pending. | Real native FFmpeg before/after hard-kill and lease-release proofs; 80 integrated and 48 independent focused tests passed. Normal commands are reaped; abnormal zombies require host PID1 reaping. |
| Generic POSIX process identity after completion | Nonreaping observation retains the leader until group cleanup and sole reap. Unsupported POSIX uses a live supervisor, bounded native-status pipe and self-stop on parent-only EOF. Detected external reaping refuses numeric signals; sole-reaper ownership is required. | Safe old-signal interception, native/forced-fallback status/FD/stream/descendant controls; 92 independent tests passed at the earlier integration checkpoint; final cleanup selection passed 81 with three native-Windows skips. |
| Raw launch failures and drainer errors | Missing/unexecutable launches return redacted typed processing errors. Cleanup error channels are bounded; original cap/callback errors survive verified cleanup. Windows unassigned suspended startup still uses its stable handle. | Actual missing/unexecutable native and forced-fallback fixtures, descriptor census and startup-handle control. |
| Cancellation shutdown transition | A lease becoming free during initial checks triggers a fresh quiescence and lease check before a terminal result. Live/reacquired cases remain unconfirmed. | Actual before failure in one of 30 repeats; after 30/30 confirmed. Three deterministic zero-signal transition controls. |
| Portable supervisor pipe EOF | After native completion the retaining supervisor closes only its own stdout/stderr descriptors before reporting native status, while preserving live group/lease ownership. Native descendant writers still hold their own descriptors and trigger the original deadline. | Actual locally forced fallback reproduces all five native-macOS failure classes; after repair 176 native-selector controls and 29 reader controls pass, with real FFprobe/FFmpeg measurements. New full/native gates below. |
| Hyperframes skipped-only integration gate | The GitHub job explicitly enables the existing real-CLI integration tests, pins the observed CLI version, bounds execution and rejects absent, empty, malformed or skipped JUnit evidence. The live project fixture rejects warning-only lint failures. | Reproduced the old opt-out as two skips with exit zero; explicit opt-in executes both tests against Hyperframes 0.8.104. Follow-up gates and scope are recorded below. |

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
`2db0b90`, documentation `f55a816`, and post-review repairs `bedcaa7`. On the earlier `f55a816` head, hosted Linux passed
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
cancellation transition failures above. The pre-stdio runtime/test/workflow checkpoint was
frozen at 1,213-file identity
`4e06562528aec90609c8a24a3976888fb99c1da833700094541544fb1ce8a831`
for its required serial gate. A post-review attempt stopped after 2,142
passes and 143 skips because the old stdin fixture expected raw `OSError`. Its
four `DEVNULL` assertions remain; expectations now require the reviewed typed
error. The 54-test helper/process selection passed. The next attempt found
that only the core toolchain resolver checked `drawtext`; the optional lane
still used the prior duplicate resolver. Both now use the same bounded probe,
with missing-filter rejection controls on both. All 267 MCPB, distribution and
architecture controls passed before this new freeze. Prior passing results remain separate checkpoints. That pre-stdio required serial
gate passed **8,281 tests, 189 skips and eight warnings in 1,927.42s**, exit
zero. The wrapper observed exit zero in 1,932.36s; all 1,213 selected files
retained the frozen identity above. Post-run census found no matching executing
native media or guardian processes. Rebuilt wheel/source archive checks pass,
with all **645 shipped Python files** matching this frozen source. Configured
Ruff check/format covers 1,135 files; Pyright reports zero errors and warnings.
The spawn-error review thread is resolved; subsequent current-source full/native results are recorded below. The separate security-review
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

## Portable supervisor follow-up

The `8328a26` checkpoint passed hosted Linux **8,256 tests, 50 skips and eight
warnings in 485.28s**, using the logged two-worker cap; Linux native **160 passed, three skipped** and
Windows **129 passed, 34 skipped** also passed. macOS failed five controls (154 passed, four
skips): four quality-reader paths waited for EOF while the retaining supervisor
still held its own stdout/stderr, and a timeout fixture equated native and
supervisor PIDs. The aggregate check was skipped. This is a failed cross-platform
checkpoint, not merge evidence.

The failure reproduced locally with nonreaping support forced off and a one-second
reader deadline: five failed and eleven passed. The supervisor now releases its
own stdout/stderr after reaping the native child, before reporting native status;
it remains live for owned group cleanup. Native descendants retain their own
writers, so genuine inherited-writer cases still time out. The timeout fixture
binds the native child's written group to the managed process and verifies the
managed process is reaped, with supervisor and native identity distinguished.
Quality child fixtures exercise both the platform-selected path and forced
portable supervision on POSIX. Their assertions and resource budgets remain.

Independent full native-selector validation passed **176 tests, three native
Windows skips in 22.95s**; the reader selection passed **29 tests**. Real FFprobe and FFmpeg
both returned five correct signalstats frames under the one-second deadline.
These Linux forced-fallback checks supplement native macOS verification.
That portable repair checkpoint had **1,213 selected files**:
`aea162427e6d61ceaacaaa7c4845a471a7920e832819a09cf96f59ef5e0e3af9`.
The current required serial and exact-head native gates pass below.

The first serial attempt on this portable repair stopped at the public-surface
privacy check after **4,866 passes, 152 skips and six warnings** in 1,132.10s:
a retained hosted receipt included a runner-home path. That path was redacted
without changing toolchain or failure evidence. All four privacy tests then
passed. The complete serial gate restarted; the failed attempt is retained as
`portable-stdio-doc-privacy-failed-serial.json`, not a passing result.

The next serial attempt exposed a scheduler-dependent timeout fixture after
**4,722 passes, 152 skips and six warnings** in 1,002.50s: a native child was
stopped before writing its PID. The fixture now waits up to five seconds for
the real owned child's explicit readiness after PID/group writes, before the
unchanged **0.1-second reader execution deadline**. The startup failure path
still closes/reaps the owned tree and streams; all original cleanup assertions
remain. Forty reader/guardian controls passed in 7.91s. This failed checkpoint
is retained as `portable-timeout-fixture-failed-serial.json`. Current selected
source is frozen at **1,213 files**, `0723d4165f26c2865b3fcf76f082a3324c9838c94b9c3bff1310c0d5f379ee0d`;
the restarted full gate passed as recorded below.

Independent readiness review passed all **29 reader controls** in 4.44s and
**ten delayed-startup cases** (five repetitions for each ownership mode), with
a deliberate0.3-second native startup delay and the unchanged0.1-second execution
deadline. The source-bound receipt is `portable-readiness-independent.json`.

## Current passing delivery gate

The required serial command passed **8,297 tests, 189 skips and eight warnings**
in **2,163.75s**, exit zero. The wrapper observed exit zero in2,168.77s. All
**1,213 selected files** retained frozen identity
`0723d4165f26c2865b3fcf76f082a3324c9838c94b9c3bff1310c0d5f379ee0d`.
The completed-run census found no matching executing native media commands or
shipped guardians. This is the current portable/readiness repair gate; earlier
passing and failed checkpoints remain separately identified. Current wheel and
source archive remain content-clean, and all **645 shipped Python files** match
the same selected source. Exact-head native CI passes in the following delivery checkpoint, with fresh
review-thread inspection. External prerequisites below are
not marked complete by this passing suite.

Post-gate documentation/public-surface/architecture/privacy controls passed
**68 tests** in17.87s. Whole configured Ruff check/format again pass for1,135
files, and canonical import identity passes. The independent configured Pyright
result remains zero errors/warnings on unchanged runtime source.

## Exact-head hosted delivery checkpoint

Head `2d903f77ee33ce371115c4fbf937e6686227b132` passed **all thirteen checks**.
Hosted Python3.14.7/FFmpeg6.1.1-3ubuntu5 passed **8,272 tests, 50 skips and eight
warnings** in603.58s with the unchanged bounded two-worker/file-grouped command.
Native Linux passed **176 tests, three skips in10.51s**; macOS **174 tests, five
skips in55.64s**; Windows **129 tests, 50 skips in8.24s**. These scoped selections
overlap other gates and are not additive. Toolcache labels are retained; precise
native FFmpeg patches are unverified because their version output is discarded
and detailed artifacts are proxy-blocked.

The tested generated merge `3ac617608911016a5c77415451607aa432b14d8a` and
head share tree `f3065a317bdde62851f748890a3f5be8cc9e449b`. The inspected
readiness receipt binds that source, archive digest
`27e60efbcd0ccaedfb899581b5b3b5a2502f5cb5e779c7b136e975337ac2ef4a` and
wheel digest `bd10fab06caaea98f75b667800368e08123052d27fb29e763e2cc47012294f81`,
which also matches the locally verified645-file build. The official pinned
validator, three clean installed runtimes, optional absent/present gates and
validated cleanup receipts pass. This checklist came from the actual aggregate
job log; its producer validates downloaded input receipts and prints the same
JSON it archives. Direct artifact downloads remain unavailable. It records
unsigned local access, human desktop review **not run** and publication **not
attempted**. Fresh review inspection finds zero unresolved threads; the separate
security bot's usage limit remains outside completed-review evidence.

[Hosted receipt](debt-closure-evidence/hosted-ci.json) retains each check and source
binding. The final documentation commit keeps selected source identity
`0723d4165f26c2865b3fcf76f082a3324c9838c94b9c3bff1310c0d5f379ee0d` unchanged; its exact-head
checks and eventual merge metadata remain observable on [PR588](https://github.com/KyaniteLabs/kinocut/pull/588).

## Merged delivery and Hyperframes follow-up

PR588 merged normally as `6f0b9cbb73efe9b8435cf4f74145bbf48702c60d`, preserving
all seven commits through final head `895096477f454fb98b0be945105a3fdc1f3aaa58`.
Actual master, final head and generated merge `dafe33f11d629378726119a0275ace80dda1702e`
share tree `3347c330e81fe3deff68cbd70169d216a7e6d4ed`. All thirteen final-head
checks passed; hosted tests passed 8,272 with 50 skips, 164 deselected and eight
warnings in 476.95s. Native Linux passed 176 with three skips, macOS 174 with five,
and Windows 129 with 50. Fresh review inspection found one resolved thread and
zero unresolved threads; the separate security bot did not complete its review.

The actual master CI run [36874422473](https://github.com/KyaniteLabs/kinocut/actions/runs/36874422473),
Integration, MCPB and MirrorSmoke workflows succeeded. The commit had 27 successful
checks and three conditional skips, including two excluded Forgejo downstream
gates. Main coverage and each Python 3.11/3.12/3.13 compatibility selection passed
8,272 tests with 50 skips and eight warnings. The main job label says Python 3.13,
but its configured and observed interpreter was Python 3.14.7. The separate slow
selection passed 159 tests with five skips; FFmpeg 6/7/8 selections each passed
125 tests. Selections overlap and must not be added. Hyperframes dependency setup
took 838 seconds; Python 3.12 FFmpeg setup took 958 seconds before its passing
tests. These are hosted dependency-install delays, not measured application latency.

Detailed logs exposed one further integration gap: the Hyperframes job succeeded
with **two skips and zero executed integration tests** because it omitted
`MCP_VIDEO_RUN_HYPERFRAMES_INTEGRATION=1`. CLI installation itself succeeded with
Node 24.21.0 and Hyperframes 0.8.104. Local safe fixtures reproduce two skips with
exit zero when opt-in is absent, versus two executed passes with explicit opt-in
and the same pinned CLI. The follow-up enables that flag before collection and
requires actual, consistent, unskipped JUnit cases, rather than treating pytest
exit zero alone as sufficient evidence. Checker-only changes are classified as
code changes so future guard repairs cannot silently skip this integration job.
Both code and Docker classification use here-strings: an independently reproduced
67,544-byte changed-file list made the previous `printf | grep -q` pipeline fail
under `pipefail` after grep's early success, incorrectly classifying code as unchanged.
The identical large-list fixture must retain its expected code/Docker results.
The CLI installation disables package
lifecycle scripts; the job, install and test phases have explicit deadlines.
The live project fixture also requires empty issues and warnings so a caught
lint launch error cannot masquerade as successful validation. This validates CLI
discovery and a small HTML project, **not browser rendering, pixel output or paid
provider quality**.

The follow-up required full serial command passed **8,330 tests, 189 skips and
eight warnings in 2,271.43 seconds**, exit zero, on unchanged **1,215-file** source
identity `202de724d5bed9457f5936473ed47d31ad0a43103ce14ff824953f5a617002d9`.
Thirty-three focused guard/classifier controls passed. Two independent reviewers
checked the actual CLI/JUnit and large-list Bash boundaries. Configured Ruff
checks and formatting passed for the selected code paths, including the new
checker. The earlier review-driven interruptions and failed writable-cache
checkpoint are retained and explicitly superseded; none is counted as a passing
full gate. After writable cache exports were restored, all 17 distribution
controls passed and the unchanged full source passed. PR588's existing gates
remain separate historical evidence.

[Follow-up local receipts](hyperframes-ci-followup/README.md) include actual
counts, command, source identity, log digest, independent review and payload
manifest. Exact-head hosted results and eventual merge metadata are recorded in
the [associated follow-up PR](https://github.com/KyaniteLabs/kinocut/pulls?q=is%3Apr+head%3Acodex%2Fkinocut-hyperframes-ci)
and its Actions runs; local passes do not establish completion of those runs.

Six issues closed with documented original-scope dispositions: 477, 481, 482,
485, 553 and 583. The retained external owner/evidence requirements are 476,
479, 487, 484, 483 and 502; Forgejo issues 499 and 488 are excluded by the user.
Missing owner appointments, private operations readbacks, directory acceptance,
site verification and historical human approval are not invented or marked done.
