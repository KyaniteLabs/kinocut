# Whole-repository UltraQA gauntlet

This is the historical implementation/review record for the work merged in
[PR #587](https://github.com/KyaniteLabs/kinocut/pull/587). Intermediate open-PR,
test-pending and running-gate statements below describe their named checkpoints.
Current follow-up work and final delivery evidence belong to the
[debt closure ledger](DEBT_CLOSURE.md).

This review starts from merged commit `e9f6cac77cb390c73c919bdcd385b775a6a3c7ef`,
tree `44806e24c1e937040f1fe4c8471ece7aca979ad9`. The scope is **the entire
repository**, including existing operations, optional integrations, public
interfaces, package/CI infrastructure, examples, skills and documentation.
It is not limited to PR #586. Its already successful delivery is recorded in
[PR validation](PR_VALIDATION.md); later working-tree repairs need separate gates.

## Disjoint primary responsibility

The [baseline](ultraqa/2026-09-30/baseline.json) and
[ownership inventory](ultraqa/2026-09-30/ownership-inventory.csv) allocate each of
1,571 tracked baseline paths exactly once, including 1,235 code/configuration
paths. Git blob identities bind the inventory to that tree. Allocation is a
responsibility assignment, **not proof that every path has been exercised**.
First matching domain owns a path; shared helpers are reviewed once by their
primary owner and exercised by consumer tests. Root owns remaining paths and
must triage them rather than silently considering them covered.

| Primary owner | Surface and whole-code responsibility |
| --- | --- |
| Root | Source probing, core picture edits and remaining media/effect/adaptor paths; coordinate the final frozen-tree gate. |
| Reliability | Process ownership, safe publication, compositor, workspace paths, projectstore/CAS and workflow/rescue lifecycle. |
| Audio | Audio engines and `kinocut_sound` measurement/mastering/mixing semantics, codecs, stream selection, timing and output metadata. |
| LLM/ML | Longform orchestration/model lifetime, transcript merge, optional matte outputs and director/model endpoint contracts. |
| Latency/cost | ASR preparation and shared signal-domain/cache measurement paths; count actual producer work and retained resources. |
| Architecture | Design analysis/autofix, D41 binding, contracts/creative/recipe/timeline/render-DAG seams and architecture limits. |
| Product/API | Every public MCP schema, CLI and Client boundary; packaging/release/CI, docs/skills, truthful claims and evidence provenance. |

Tests are assigned by their primary contract while orthogonal checks cross
owners. New files and later repairs must join the final source inventory; the
baseline manifest does not pretend to hash code that did not yet exist.

## Orthogonal adversarial dimensions

| Dimension | Concrete probes and required interpretation |
| --- | --- |
| Input/domain | Missing/empty/malformed values, booleans masquerading as numbers, NaN/infinity/overflow, invalid enums and unknown top-level arguments. |
| Media truth | Audio-only/no-audio/multiple streams; rotation, offsets, picture versus container duration, variable timestamps, bit depth/range and real codec/container pairing. |
| Filesystem/provenance | Source replacement, same-size edits, symlink/hardlink aliases, parent swaps, confinement and stale manifests; bind claims to actual bytes and source identity. |
| Publication | Inject partial writes, timeout, callback/postflight failures and cancellation; prior destinations survive and staging is cleaned. Separate file atomicity from multi-file transactions or crash durability. |
| Processes/resources | Actual selected executables, child kill/reap, verbose/no-newline output, bounded producers, retained diagnostics, memory/disk limits and success-only cache reuse. |
| Interfaces/transport | SDK argument validation and generated schemas, real stdio serialization, CLI exit/envelope behavior, Client aliases, async context injection and declared nested mappings. |
| Optional backends | Missing dependencies, malformed model output, local/cloud endpoint boundaries and unavailable inference. Skips or synthetic doubles never establish accuracy or backend callability. |
| Delivery/evidence | Exact Git SHA/tree, lock/SDK/FFmpeg versions, artifacts and source hashes, CI selection, package/shim identity, external listing drift and independently reviewed producer instrumentation. |

These dimensions form a checklist, not a claim that every possible Cartesian
combination has run. A passing discovery check does not certify rendering,
perception, privacy or creative acceptance.

## Reproduced findings and observed checks

| Finding/check | Observable evidence and current status |
| --- | --- |
| MCP silently ignored undeclared parameters | A real stdio `video_info` call accepted `unsupported_parameter=true`; all 201 schemas initially omitted an additional-property restriction. Client/CLI unknown-parameter guards already differed. The shared registration now rebuilds the SDK argument model with `extra=forbid` and derives its schema from that model. A subsequent real stdio mixed-invalid call reproduced private submitted values being echoed by SDK validation. Argument prevalidation now returns bounded JSON `validation_error`/`invalid_parameter` with `isError=true` for missing, typed, nested or unknown argument errors; handler exceptions remain outside this translation. [Before/after evidence](ultraqa/2026-09-30/mcp-validation.json) binds the repair to its working-tree sources. [Independent review](ultraqa/2026-09-30/mcp-independent-review.json) checked the final argument/handler boundary; the final aggregate gate remains separate. |
| Staging guard rejected its own postflight-read output | The first broader API/workflow run reported **22 failures, 251 passes**. `_atomic_output` treated a staged file read for verification as an original input, rejecting resize and variant/resume workflows. [Failure log](ultraqa/2026-09-30/boundary-first-run.log) retains the concrete cases. Reliability repaired the publication boundary. A fresh [consumer rerun](ultraqa/2026-09-30/boundary-validation.json) passed **273 tests**; this working-tree checkpoint remains separate from the upcoming frozen-tree aggregate gate. |
| Fifteen existing core writers could lose prior destinations | Root's partial-write injection reproduced the pattern beyond PR #586 in crop/rotate/watermark/fade/reverse/preview/overlay/split-screen/mask/normalize. Two watermark named-position cases also produced literal `{margin}` expressions. Root expanded the same adversarial scope to filter/text/subtitles/stabilize/merge, including single-clip copy. Root supplied a [91-test focused pass](ultraqa/2026-09-30/root-final-focus.log) across core geometry/publication, probing/resizing and architecture. Later fade-origin refinements need their separate gate; this owner-supplied checkpoint is not the final frozen-tree aggregate. |
| Independent native-six attribution was not bound to execution | The original four-case harness patched `_run_command`, while the direct FFmpeg runner bypassed it. [Supersession](runtime-allocation/audio-timeline-ci/corrections/supersession.json) archives reconstructed instrumentation, corrected script/rows, actual subprocess paths, binary hashes and source bindings. Four corrected cases passed, but the mixer source hash differs from the merged baseline. The 37-case native suite, separate eight-case native matrix and actual hosted FFmpeg-six CI are unaffected. |
| Live catalog/schema/transport coverage | All **201** input schemas pass structural JSON Schema checks and every required parameter is declared; **173** flat CLI commands are registered. Real stdio initialization, listing and metadata discovery succeeded. Client mix/duck/normalize aliases agree with their declared contracts. These checks do not invoke every optional backend. |
| Packaging and publication infrastructure | **217 tests passed** across package writer/models, onboarding, MCPB supply-chain/staged/native-launcher contracts, release cutover, lazy imports, workflow infrastructure and privacy checks. [Log](ultraqa/2026-09-30/packaging.log) preserves the run. Native-launcher unit contracts are not a real desktop installation. This log predates the environment refresh; a later source gate must identify its own tree. |
| MCP repair consumers | **55 tests passed** across the new argument contract, MCP entry, public surface and Client audio contracts. [Log](ultraqa/2026-09-30/mcp-argument-gate.log) includes actual stdio negative/valid optional calls, async/context behavior, arbitrary declared mappings, mixed/missing/nested invalid arguments, no submitted-value echo, numeric-boolean rejection with valid boolean/string controls and handler-error separation, deep serialized JSON and integer-digit parser limits. Focused counts overlap and are not additive. |
| Serialized argument parser limits | Independent review reproduced a raw recursion exception for deeply nested serialized dict/list arguments. The same seam also reproduces Python's JSON integer-digit `ValueError`. Argument preparation now returns bounded `invalid_parameter` for both, including mixed unknown inputs; the actual stdio gate and handler-error separation controls pass. [Independent before/after evidence](ultraqa/2026-09-30/independent-api-geometry/INDEPENDENT-REVIEW.json) records reviewer probes. |
| Numeric boolean schema parity | [Actual stdio before/after](ultraqa/2026-09-30/mcp-boolean-repro.py) showed schema-invalid `bins=true` previously succeeded as one bin. A numeric-only argument-model validator now rejects booleans before coercion while preserving explicit boolean fields and existing numeric-string compatibility; the focused gate covers both. |
| Signalstats and ASR frontend resource use | [Source-bound trials](ultraqa/2026-09-30/signal-asr/REPORT.md) retain producer scripts, raw results, fixture metadata and source hashes. The signalstats trial reduced parent peak RSS 94.62→42.98 MiB with eight means exactly equal; the two ASR frontend trials reduced parent RSS 193–206→56 MiB with separate child RSS 48–49 MiB and added startup cost. Anti-alias tone controls improved; model/corpus/WER and simultaneous aggregate RSS are excluded. Owner reports 192 passes/5 skips plus 12 preprocessing passes; a separate final formatting manifest links seven formatting-only source updates to the original measured-source manifest, with 63 post-format tests passing. The final sequential aggregate passed as recorded below. |
| Transcript/model/source boundaries | Owner reports 119 longform, 36 matte/reframe and 143 sphere/model focused passes (overlapping selections). Finite/source-bound timing, repeated-event matching, invalid model output, aliases before inference, endpoint opt-in, callback isolation and source-identity publication controls are covered. [Reviewer notes](ultraqa/2026-09-30/llm-ml-review-current.md) preserve independently reproduced fade/design defects for root/architecture repair. No model quality or immutable kernel snapshot claim applies. |
| Configured design media executables | Reviewer reproduced design analysis bypassing configured binary paths. Root repaired probe/filter routing and source-bound analysis; the [configured-media proof](ultraqa/2026-09-30/owner-gates/design-configured-media-proof.json) records 78 passes, actual configured FFmpeg/ffprobe with empty PATH, with/without audio and source hashes. |
| Audio timing, publication and rescue boundaries | [Audio owner/reviewer findings](ultraqa/2026-09-30/audio/AUDIO-FINDINGS.md) record primary-stream extent/origins, presentation-packet picture duration, bounded fallback producers, strict parameters and staged error-sensitive AAC verification. Scoped 87 passes/1 skip and rescue 24 passes are separate from the final aggregate. Native-offset/delay/loop fade controls pass. The completed [attachment/API gate](ultraqa/2026-09-30/audio/attachment-final.log) records 160 passes and one intentional None-delay invalid-cell skip. Decimal rescue boundaries tolerate operand ULP roundoff without broadening the existing policy. |
| Architecture and capability contracts | Client masks and CLI quality renderables retain their public behavior after focused extraction. Design measurements share source-aware caches and disclose unavailable/approximate RGB; autofixes use shared staged publication. Workflow/D41 capability/version paths respect selected binaries and success-only unchanged-identity cache reuse; stat identity is not a cryptographic content digest. |
| Documentation drift | Corrected the active tool-reference header from published 1.15.2 to canonical 1.15.3. A repository-wide local-target scan covered 278 tracked Markdown/text documents; its only missing target was this new ledger before creation. A [fresh scan](ultraqa/2026-09-30/documentation-target-audit.json) including this ledger checks 284 documents with zero broken local targets. Historical release sections remain historical. |

The initial consumer run crossed concurrent implementation changes, so it is a
working-tree regression observation, not a claim that the merged baseline failed.
The [registered-schema audit](ultraqa/2026-09-30/api-contracts-current.json) likewise binds its current source state separately
from the baseline. Source-file and artifact identities must be refreshed after
all owners freeze before the final whole-suite result is claimed.

## Read-only GitHub backlog and delivery

Fresh API reads confirm **34 open issues and five draft PRs**:
[issue inventory](ultraqa/2026-09-30/open-issue-inventory.json) and
[exact-head draft checks](ultraqa/2026-09-30/pending-pr-checks.json).
PRs #579/#577/#567 each have 13 successful checks on their inspected heads.
#575/#573 expose zero check-run records. Fresh [exact-head Actions queries](ultraqa/2026-09-30/pending-pr-actions.json) also return zero workflow runs; this is absent evidence, not failed CI or an inferred approval block. The [GitHub-only follow-up](github-backlog/2026-10-01/REPORT.md) reviews all 34 bodies and in-scope comments against the merged baseline: 20 original-scope closure candidates at the read-only checkpoint; subsequent root-authorized state-only results are recorded separately in that report. Root subsequently completed those 20 state-only closures with no comments or draft-PR changes. Fresh site403 retains #479; platform/feature/owner gates remain distinct. Forgejo is excluded by the latest user instruction, not a current blocker.
All five remain drafts; their reviewed fixes
were adapted separately in #586. No comments, closures, approvals or merges were
performed during this read-only review.

#586's final head `a6ff3ad3bb186f3f3f63900c7150da9a1ee025bf` has **13/13
successful checks** and merged at `2026-09-30T21:50:42Z`; see
[delivery evidence](runtime-allocation/audio-timeline-ci/merged-delivery.json).
Those results do not validate subsequent UltraQA working-tree changes. Published
package identity remains distinct from source changes even when version strings
coincide. Model/host quality, speed and zero-egress claims need their own evidence.

The environment refreshed on 2026-10-01 and erased temporary `/tmp` tools/logs.
Already archived evidence remains intact; fresh gates are retained under
`/workspace/.cache/kinocut-qa` and copied into this ledger. Lost temporary
artifacts are not reconstructed as original bytes or treated as new results.

Publication review also reproduced a staged-leaf writer-open symlink attack after
the first helper repair. Reliability now binds FFmpeg output and JSON writes to
the owned staged descriptor. Its focused gates do not establish native Windows
or macOS behavior; hostile writable directories retain disclosed identity-to-rename
and Windows close-to-rename windows. Composite media and plan files remain
independently atomic, not a two-file transaction.

## Closure requirements

Each author supplies a concrete reproducer, fix, focused regression and source
identity. Another active review context checks the changed behavior before a
finding is closed. The review and verify workflows prefer existing tests and
narrow direct checks, and permit honest unresolved results.

Root reports the expanded native-boundary/workflow selection passed **106 tests**,
with **three native-Windows skips** on this Linux host; [log](ultraqa/2026-09-30/native-boundary-workflow-focus.log) records the run.
The new cross-platform CI selection will exercise actual Windows/macOS behavior,
but at this pre-publication checkpoint no new hosted result is available yet. Hosted outcomes belong to the eventual PR exact-head checks.

All source authors froze before the first aggregate attempt. Root recorded 1,188
source/test/configuration file identities in its frozen-source manifest (inventory SHA256
`536632243a5a29b92705a53597841c6b2dd1efab9f075fd5e8030d0f30826f00`).
The [first aggregate attempt](ultraqa/2026-09-30/full-gate-attempt-1/result.json) failed during collection in 0.78 seconds, **zero tests executed**, exit 1: body-swap imports the removed `_av_end_delta` rescue helper. Its failed-tree source manifest/log remain intact. Audio restored the shared compatibility helper; 42 verifier/body-swap tests passed and all 8,181 tests then collected successfully. [Collection log](ultraqa/2026-09-30/audio/all-tests-collection.log) is not execution of those tests. The [second full attempt](ultraqa/2026-09-30/full-gate-attempt-2/result.json) ran against 1,188-file identity `182547c2af395f81b48d3d1e629dc8cbdc3e87257555dd7c4a31d290c61ab170`. It failed with **1 failed, 1,368 passed, 142 skipped** in 370.47 seconds, exit 1: `test_real_encoding_timeout_preserves_destination[False]` did not raise its expected timeout. The extracted progress runner did not retain caller deadline binding. Reliability repaired explicit deadline forwarding; the separate [focused repair](ultraqa/2026-09-30/owner-gates/progress-deadline-repair.json) passed 73 tests with three native-Windows skips. The [third attempt](ultraqa/2026-09-30/full-gate-attempt-3/result.json) uses a separate source identity `83be7eb0b3756f877e97a55b7e458532f83135e0ca0e474893c07ea0fe59cb41` and also failed: **1 failed, 1,628 passed, 142 skipped, four warnings** in 467.11 seconds, exit 1. `TestBuildAudioFilters::test_fade_in_only` expected existing `st=0` grammar while the new helper emitted `st=0.0`; audio owns grammar and explicit fade-length/caller-window compatibility repairs without weakening tests. Root broadened all-tests integration with a [parallel preflight](ultraqa/2026-09-30/parallel-preflight/result.json), frozen identity `6f2a04d0bbec046f4a7c6bd4dabd76b3806a41f4f635b28b45a878c945169d82`: **14 failed, 7,981 passed, 189 skipped, eight warnings** in 792.32 seconds, exit 1. Failures cover tiny-resize/split compatibility, stereo-ASR ingress, centralized constant exports, invalid-quality-metadata retry and explicit-stdin source inventory. Assigned repairs precede the next source freeze. Root’s legacy tiny-crop assertion now requires typed `invalid_crop` for intentional odd-dimension rejection; the split control uses documented `top-bottom` instead of an invalid `stacked` fallback. These expectation updates preserve the new strict policies rather than claiming every failure was a production bug. The parallel result does not replace the required sequential gate. The [fourth required sequential attempt](ultraqa/2026-09-30/full-gate-attempt-4/result.json) passed **8,005 tests, 189 skipped, eight warnings** in 1,722.15 seconds, exit 0, on frozen 1,188-file identity `5ae658513cdff7be42d2965572ed0c0a2da5233a5bb33c129844dbf384499966`, with the runner confirming unchanged source (1,727.39 seconds wall time). Geometry/policy repairs passed 36 tests, explicit-stdin source inventory passed nine, and [ASR/export/cache repairs](ultraqa/2026-09-30/signal-asr/manifest-compatibility-repair.json) passed 106; pinned Ruff check/format pass for 1,110 files and canonical import identity passes. The independent ASR compatibility selection passes 47 tests in 3.46 seconds; its source/error repro logs are separately retained. Original resource benchmark manifests remain historical measured snapshots, not rerun after these compatibility repairs. Audio separately repaired legacy helper/builder grammar without weakening delay/native-offset/loop controls; [legacy integration](ultraqa/2026-09-30/audio/legacy-audio-integration.json) passed 444 tests with 56 skips and five warnings in 531.67 seconds. Pinned Ruff check/format for 1,110 files and canonical import checks passed on attempt 2, but cannot convert its failed test outcome into aggregate success.

The required sequential full-suite gate **passed after three failed sequential attempts and a failed parallel preflight**. Pinned Ruff check/format and canonical import checks also passed. Implementation is banked at `258cb0076f9ade77c41f6a528cf4c62d0745543a`. The earlier 7,451-test local checkpoint and exact-head
hosted suite remain valuable historical evidence, not forecasts of this gate.
Windows-specific publication behavior, optional provider execution and a real
host model session require their own platform/backend evidence.

## Final static source allocation

The [implementation-bound inventory](ultraqa/2026-09-30/final-runtime-allocation/allocation.json) records 640 runtime files: **96.9853% deterministic, 2.5930% LLM prose, 0.4217% traditional ML** by its disclosed authored-source units. The revision is `258cb0076f9ade77c41f6a528cf4c62d0745543a`; documentation paths were still working-tree inventory: 1,609 tracked files and 1,766 total tracked/unignored paths, distinct from the 1,571-path original baseline. Earlier allocation snapshots remain historical. These percentages do not measure execution time, cost, latency, usage or quality.

## PR 587 initial hosted checkpoint

At head `dddf3e1c88b9c3016b8fd9673fc589e9a5901a59`, the [initial hosted run](ultraqa/2026-09-30/ci-attempt-1/result.json) had thirteen total checks: ten successful, two failed and one skipped aggregate. The earlier first snapshot had ten successes, one failure, one skip and the hosted test still pending; the completed snapshot is archived separately. Native Windows had 31 passes, 18 skips and one test-only dead-PID `os.kill` assertion failure after subprocess cleanup. Hosted Python 3.14.7/FFmpeg 6.1.1 had four failures, 7,976 passes, 50 skips and 164 deselections in 1,032.56 seconds: the all-`0xff` AAC mutation did not produce the expected decoder rejection. At that initial checkpoint, a fixture-only hypothesis was under review and the fifth sequential gate had not started; both are superseded by the actual decoder comparison and frozen repair below. Corrected hosted success is not asserted. Earlier local attempt4 and merged586 receipts remain separately scoped.

The initial AAC-fixture-only hypothesis was superseded by actual pinned native FFmpeg 6.1.1 reproduction: decoder errors can still return exit zero despite `-xerror`, including the original mutation and other invalid AAC syntax. This establishes a production decode-rejection policy defect. A proposed `-max_error_rate 0` repair was then tested and superseded by the severity-based repair below; it does not ensure decoder-error rejection. The initial three-file native CI selection contained 50 cases: Linux47pass/3skip, macOS46pass/4skip, Windows31pass/18skip/1fail. The earlier local106-test selection included56 additional workflow/other controls and is distinct.

Further actual native6 controls superseded the proposed flag-only repair: `-max_error_rate 0` and `-err_detect explode` still permit zero-exit decoder errors. The [focused CI repair evidence](ultraqa/2026-09-30/ci-repair/result.json) records severity-tagged rejection in existing audio analysis/render/postflight passes, including ANSI-colored diagnostics, with no additional production decode. Official native6 provenance, raw flag/control scripts and independent color-bypass review are retained; compiler/source clones and private redirect logs are excluded. Captured subprocess stderr is collected before bounded public diagnostics, so a hard transient stderr-memory cap is not claimed. The interim native6 colored controls passed 74/1 skip, installed7 audio155/1skip and diagnostic tags7; those raw results remain historical, superseded by final source-bound controls below. Windows test-only repair passed 16 locally and 16 independently.

Final scoped audio source preserves actual zero exit status in the typed failure; a severity-prefix regex handles ANSI SGR directly, accepts nonfatal info/warning `[error]` literals, and extracts at most 4,096 UTF8 bytes at complete codepoints without a whole-log split/copy. The [final manifest](ultraqa/2026-09-30/ci-repair/aac-corruption-review/manifest-final.json) binds actual native6 colored 75 passes/1 skip in 22.48 seconds and installed7 audio 159 passes/1 skip in 106.07 seconds. Independent native6 plain/color valid and corrupt controls, bare severity tags and nonfatal literals are retained. Earlier after-operation logs reporting `ffmpeg_exit1` belong to an interim wrapper; final controls preserve actual `ffmpeg_exit_0`. The [fifth required sequential gate](ultraqa/2026-09-30/full-gate-attempt-5/result.json) is now running on frozen 1,188-file identity `7f21901bb4af79fe9041d39348b0329d3b7e8e43869fc653b8c42121ac1b2fd4`; no completed count or corrected hosted result is asserted.

## Repaired implementation and final local gate

Repair implementation `c28f7f30932212606eba14242f56bdbf20fff76e` passed the [fifth sequential gate](ultraqa/2026-09-30/full-gate-attempt-5/result.json): **8,013 passed, 189 skipped, eight warnings** in 1,728.34 seconds, exit0. Runner wall time was 1,733.56 seconds; the 1,188-file source identity `7f21901bb4af79fe9041d39348b0329d3b7e8e43869fc653b8c42121ac1b2fd4` remained unchanged. [Pinned Ruff check/format and canonical import](ultraqa/2026-09-30/full-gate-attempt-5/statics/result.json) passed on that identity. Earlier running/not-started statements above describe diagnostic checkpoints, superseded by this result. The [new static inventory](ultraqa/2026-09-30/final-runtime-allocation-5/allocation.json) binds 640 runtime files to this implementation: 96.9866% deterministic, 2.5918% prose, 0.4216% traditional ML; 1,777 tracked paths and 1,811 tracked/unignored inventoried paths. Prior 258cb allocation remains historical. These authored-source units are not execution cost, latency, usage or quality. Corrected exact-head hosted outcomes are **pending at this pre-push checkpoint**; subsequent outcomes belong to PR587 exact-head checks, not a forecast here.
