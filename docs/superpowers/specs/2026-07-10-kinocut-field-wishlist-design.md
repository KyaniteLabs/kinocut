# Kinocut Post-1.7.0 Field Wishlist Design

**Status:** Approved design for Forgejo issue #126

**Scope:** Implement the twelve ranked production findings from the 2026-07-10
field postmortem without publishing a new Kinocut release.

**Estimate:** Epoch PERT expected 78 hours; 95% confidence 42–114 hours.

## Outcome

Kinocut will cover the production operations that currently force callers into raw
FFmpeg, emit receipts and temporal review artifacts for those operations, expose a
discoverable command surface, and diagnose stale pre-rename installations. Existing
MCP, Python, and flat CLI entry points remain compatible. The single intentional
default change is loss-proof audio addition: preserving the video duration becomes
the default, while explicit `shortest` behavior remains available.

Implementation ends after five reviewed merge requests land and the issue #126
acceptance matrix passes. No version bump, tag, package upload, Smithery or directory
submission, Forgejo release, or other release action is authorized by this design.

## Design Alternatives

### Selected: cohesive merge train

Build shared duration, receipt, review-artifact, and registry contracts once, then
deliver the wishlist in five independently usable merge requests. Keep flat commands
as compatibility aliases while making namespaced commands the recommended surface.

This minimizes duplicate FFmpeg construction, gives clip reuse and QA artifacts one
provenance model, and fixes the two production footguns before larger product work.

### Rejected: twelve isolated features

This maximizes initial parallelism but duplicates probing, path safety, receipts,
FFmpeg filters, and error semantics. It also makes the clip registry and bed audition
rely on special-case outputs rather than a common substrate.

### Rejected: kernel-first rewrite

Building all wishlist items on the planned durable kernel would delay the two current
production defects and couple this work to unresolved kernel lifecycle decisions. The
wishlist remains additive to the shipping engines. Future kernel adapters may wrap
these primitives without changing their public contracts.

## Global Constraints

- Reuse `ffmpeg_helpers.py`, `validation.py`, `limits.py`, and `defaults.py`; do not
  duplicate shared helpers or hardcode runtime defaults.
- Escape every user-controlled FFmpeg filter value with the existing audited helper.
- Use Kinocut custom errors, bounded subprocesses, validated input paths, and truncated
  processing failures.
- Keep modules at or below 800 lines and functions at or below 80 lines.
- Preserve existing flat CLI, MCP, Python client, compatibility import, environment,
  and receipt surfaces unless this document explicitly changes behavior.
- Receipts and examples must not disclose private absolute paths, credentials, or
  unrelated environment details.
- Generated QA artifacts support human review; they do not claim to prove creative
  quality or publication readiness.
- Optional ML-backed capabilities fail closed with an explicit unavailable reason and
  never download a model or select a remote provider implicitly.
- Every merge request requires red/green regression evidence, focused real-FFmpeg
  integration tests, public-surface parity tests, and the full repository suite.

## Shared Contracts

### Duration policy

Duration-sensitive operations use a two-value public policy:

- `keep_video` is the default. The output duration matches the probed video duration.
  Short audio is padded with silence; long audio is trimmed.
- `shortest` preserves the legacy shortest-stream behavior and must be explicitly
  requested.

The result reports input video duration, input audio duration, output duration,
selected policy, whether padding or trimming occurred, and warning codes for any
duration adjustment. A post-render probe verifies the declared policy within the
existing duration tolerance. A mismatch is a processing failure, not only a warning.

### Edit receipt v1

Receipt-producing operations accept an optional `save_receipt` path and return the
receipt in structured results. The receipt contains:

- `schema_version: 1` and `receipt_kind: "edit"`;
- operation name and normalized parameters;
- ordered inputs with safe display name, media role, SHA-256, duration, and relevant
  stream metadata;
- output with safe display name, SHA-256, duration, and stream metadata;
- toolchain fingerprint and Kinocut version;
- warning codes, review-artifact references, and `human_review_required`;
- operation-specific verification, including audio packet identity when promised.

Receipt paths use the existing artifact-path safety and atomic JSON writer contracts.
Absolute source locations remain internal and are never serialized. Existing workflow
and layer-plan receipt kinds are not rewritten.

### Review artifacts

Review artifacts share a compact descriptor: artifact kind, safe relative path,
SHA-256, generation parameters, source hash, and human-review status. Motion strips,
text-drift crops, and bed-audition reels use this descriptor in receipts and JSON CLI
output.

### Local registry

The approved-clip registry is a versioned local JSON document written atomically under
the Kinocut data directory unless the caller supplies a validated registry path. Each
entry has a stable clip ID, clip hash, semantic beats, provenance receipt hash, QA
artifact hashes, verdict, notes, and timestamps. Updates use compare-before-replace;
corruption, hash mismatch, duplicate clip identity, or conflicting edits leave the
last valid registry untouched.

## Subproject 1: Safety Fixes

### Loss-proof `add-audio`

The engine, MCP tool, Python client, and CLI gain `duration_policy`, defaulting to
`keep_video`. CLI `--shortest` is a compatibility convenience that selects
`duration_policy=shortest`; contradictory options fail validation. The engine probes
both sources before constructing FFmpeg arguments and verifies the result afterward.

Existing callers that omit the new parameter receive the safer behavior. This is an
intentional default change because the previous behavior silently removed video
content in unattended renders.

### ASS and dimension-aware subtitle rendering

Subtitle inputs accept `.srt`, `.vtt`, and `.ass` case-insensitively. ASS inputs render
through libass without discarding authored PlayRes or style information. SRT and VTT
inputs probe the target video and pass its real dimensions to libass so vertical video
does not inherit the 384×288 script-resolution default.

Unsupported subtitle extensions, missing video dimensions, invalid ASS content, and
filter construction failures use existing Kinocut validation or processing errors.
All paths, styles, and filter values remain escaped.

## Subproject 2: Receipt Substrate

Merge and edit-style operations gain optional edit receipt generation without changing
their default return compatibility. Merge receipts preserve ordered inputs, per-clip
durations, transitions, normalization decisions, output duration, and output hash.

The receipt writer, safe artifact path validation, canonical hashing, privacy scan, and
inspection summary live in focused modules. Higher-level wishlist primitives consume
this substrate rather than implementing private receipt formats.

## Subproject 3: Production Primitives and QA Artifacts

### `audio-bed`

`audio-bed` builds on the existing sidechain-ducking engine. It accepts a video or voice
source, one music bed, loop enablement, loop crossfade, fade-out, target loudness, and
output path. Field-proven defaults are sidechain threshold `0.02`, ratio `5`, attack
`25 ms`, release `450 ms`, loop crossfade `1.5 s`, fade-out `2.2 s`, and target
`-16 LUFS`.

The command probes sources, loops only when necessary, crossfades loop seams, ducks the
bed beneath speech, normalizes the result, and emits an edit receipt. It never silently
substitutes the simpler mixer when the sidechain filter is unavailable.

### `body-swap`

`body-swap` replaces the video track beneath approved source audio. It accepts approved
audio/video input, replacement video, `video_policy` (`pad` or `trim`), output, and
optional receipt. Audio uses stream copy. Verification compares packet-level audio
hashes between the approved input and output and fails when identity is not preserved.

The default `video_policy` is `pad`: a short replacement holds its final frame to the
approved audio duration; a long replacement is trimmed. Explicit `trim` also trims a
long replacement to the approved audio duration, but rejects a short replacement
instead of truncating approved audio. Full audio packet identity is therefore required
under both policies.

### `motion-strip`

`motion-strip` emits one PNG containing evenly sampled full-frame thumbnails across the
clip. Callers choose frame count and tile columns within audited limits. The default is
eight samples including near-start and near-end frames. The JSON result includes exact
sample timestamps and a review-artifact descriptor.

### `text-drift-check`

`text-drift-check` accepts one or more declared normalized label regions and samples
full-resolution crops at 25%, 50%, 75%, and 95% of real clip duration by default.
Regions and timestamps are validated. The command emits individual lossless crops, a
contact sheet, and a manifest. It does not invent OCR confidence or pass/fail claims.

### `bed-audition`

`bed-audition` consumes a voice source and two or more candidate beds. It creates one
labeled reel with approximately twelve seconds per bed, mixed through the same
ship-level ducking defaults as `audio-bed`. The reel, segment timing, bed hashes, and
labels are receipt-backed and always require human review.

## Subproject 4: Voice Gates and Approved Clips

### `voice-style-check`

The style gate uses local ASR segments, clamping every segment start and end to the
probed audio duration before calculating metrics. For each valid segment it measures
mean loudness and speech rate. Defaults flag loudness deviation greater than `4.5 dB`
from the track median or speech rate outside `1.8×` of the median rate.

Unavailable transcription produces an explicit capability result. Empty, zero-length,
or fully clamped segments are excluded with warning codes rather than creating false
pace failures.

### `voice-identity-check`

The identity gate requires an explicit reference speaker sample and a locally available
speaker-embedding capability. It computes per-segment reference similarity and
neighbor/median similarity. Defaults are minimum reference similarity `0.75` and
minimum pair similarity `0.80`.

Embedding dependencies remain optional, doctor-visible, and locally capability-gated.
No model download occurs inside the command. Results identify suspect timestamps and
scores while preserving the requirement for human listening review.

### `clip-index`

The namespaced `kino clips` surface provides `add`, `list`, `find`, `verify`, and
`remove`. Adding a clip requires a file hash, at least one semantic beat, provenance or
an explicit `provenance_unavailable` reason, and a QA verdict. `find` ranks exact beat
matches before normalized tag matches and never silently returns an unverified clip as
approved.

## Subproject 5: Operator Surface

### Namespaced CLI

The recommended top-level surface becomes concise namespaces such as `kino audio`,
`kino captions`, `kino qa`, `kino voice`, `kino clips`, `kino workflow`, `kino hf`,
`kino ai`, and `kino fx`. Existing flat command names remain functional aliases and
retain their arguments. The top-level help shows namespaces, high-frequency intent
verbs, and a discoverability pointer for the compatibility command index.

MCP tool names and Python methods stay stable. New primitives receive matching MCP,
Python, flat CLI, and namespaced CLI coverage.

### Agent-mode output

When stdout is not a TTY and the caller did not explicitly select a format, commands
that return structured results emit JSON. Explicit `--format text` preserves text
output; explicit `--format json` remains unchanged. Commands that stream progress keep
progress on stderr and reserve stdout for the final structured result.

### `doctor --migrations`

Migration diagnostics are read-only by default. They inspect known Kinocut and legacy
configuration locations for superseded MCP registrations, missing executable targets,
stale environments, conflicting installed versions, and known legacy assembler paths.
The report includes severity, evidence safe for local display, and exact remediation
commands. It never rewrites or deletes configuration automatically.

## Error Handling

- Validate media paths and stream requirements before FFmpeg execution.
- Reject unsafe receipt, registry, artifact-directory, subtitle, and model paths using
  existing centralized validators.
- Reject contradictory duration policies, invalid crop regions, excessive sample
  counts, unsupported subtitle types, empty bed lists, and non-finite thresholds.
- Translate FFmpeg timeouts and failures through `ProcessingError`; never expose raw,
  unbounded stderr.
- Represent optional capability absence as an explicit unavailable result when the
  operation is a check, and as a validation error when the caller requested a render
  that cannot execute.
- Fail registry writes atomically. A failed update leaves the prior file byte-identical.
- Preserve human review as required whenever an operation involves motion quality,
  speaker identity, or music taste.

## Test Strategy

Each subproject follows strict red/green TDD and carries tests at five levels:

1. unit tests for validation, policies, hashing, serialization, and filter construction;
2. focused real-FFmpeg tests for duration, subtitle geometry, audio stream copy,
   ducking, strips, crops, and audition reels;
3. CLI, MCP, and Python parity tests for every new public argument and result;
4. security/privacy tests for paths, filter escaping, bounded subprocesses, receipts,
   registry atomicity, and optional-capability behavior; and
5. the full repository suite plus import, Ruff, FFmpeg 6/7/8 CI, public leak audit, and
   public-surface drift checks before merge.

Field acceptance fixtures reproduce the original failure classes: shorter audio must
not remove an outro; vertical subtitle sizing must use real dimensions; body-swap must
preserve audio packet identity; temporal artifacts must include late frames; ASR ends
past EOF must not create false pace failures; and a low-similarity identity segment
must be surfaced when the optional embedding fixture is available.

## Delivery Order and Ownership

1. **Safety fixes:** `add-audio` duration policy and subtitle support.
2. **Receipt substrate:** edit receipt v1 and merge/edit integration.
3. **Production primitives:** `audio-bed`, `body-swap`, `motion-strip`,
   `text-drift-check`, and `bed-audition`.
4. **Analysis and registry:** voice gates and approved-clip registry.
5. **Operator surface:** namespaces, agent-mode output, migrations, final parity and
   field-fixture gate.

Each item is a separate reviewed merge request based on the preceding merged result.
One task owns one focused artifact set and commit unit. Shared files such as CLI routing,
server registration, public manifests, and docs are changed in delivery order rather
than concurrently. Implementation workers use isolated worktrees and do not touch the
unrelated dirty recovery checkout.

## Completion Gate

Issue #126 may close only after all twelve requirements map to passing tests and the
final field-fixture report shows no raw-FFmpeg workaround is required for audio
addition, ASS subtitle burn-in, ducked beds, or body-swap. The closeout receipt must
list merge commits, test counts, known optional-capability limits, and remaining human
review requirements.

After that receipt, stop before release and await explicit user direction.
