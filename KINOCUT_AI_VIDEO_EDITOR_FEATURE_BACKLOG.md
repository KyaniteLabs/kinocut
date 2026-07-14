# Kinocut AI-Video Editor Feature Backlog

## Product thesis

Traditional editing assumes the camera produced evidence. AI-video editing assumes every frame is a proposal.

Kinocut should become the trusted operating system for turning uncertain generated footage into intentional, reviewable, reusable media. Its canonical loop is:

```text
specify
  -> ingest
  -> inspect
  -> classify
  -> salvage or regenerate
  -> assemble
  -> verify
  -> review
  -> register what worked
```

The editor's central responsibility is adjudication: deciding what is stable, intentional, trustworthy, and valuable enough to keep.

## P0 — Core workflow and safety

### 1. Generation Acceptance Spec

Define required subjects, actions, visual rules, exact text, forbidden defects, target formats, and review criteria before editing begins.

### 2. AI Asset Ingest

Import generated clips with stable IDs, technical metadata, model information, prompts, generation settings, references, and usage rights.

### 3. Immutable Source Preservation

Preserve original generated assets and hashes before normalization, trimming, repair, or transcoding.

### 4. Media Preflight

Probe duration, streams, resolution, frame rate, rotation, codecs, color properties, loudness, and file integrity before editing.

### 5. Explicit Clip Verdicts

Record one structured verdict: approved, approved with trim, background-only, repairable, still-frame salvage, rejected, or regenerate.

### 6. Defect Taxonomy

Attach structured labels such as text drift, identity drift, object mutation, warping, flicker, unwanted camera motion, continuity failure, or late-frame degradation.

### 7. Approved-Element Locking

Mark audio, clips, graphics, timings, or timeline sections as approved and prevent later operations from changing them silently.

### 8. Receipt-Backed Editing

Emit receipts containing ordered inputs, hashes, in/out points, transformations, warnings, output duration, output hash, and toolchain versions.

## P1 — AI-specific visual inspection

### 9. `kino motion-strip`

Produce a tiled temporal contact sheet showing representative frames across an entire clip.

### 10. `kino late-frame-qa`

Automatically inspect the beginning, middle, late, and final portions of generated footage.

### 11. `kino text-drift-check`

Extract full-resolution crops of declared text or logo regions at configurable timeline percentages.

### 12. `kino temporal-inspect`

Generate a standard package containing a normal-speed preview, muted preview, motion strip, key-frame samples, region crops, basic frame differences, and technical metadata.

### 13. Loop Integrity Check

Compare opening and closing states and identify broken loops, discontinuities, or late mutations.

### 14. Frozen, Black, and Corrupt Segment Detection

Find unexpectedly static, black, duplicate, missing, or unreadable frames.

### 15. Motion Intent Check

Flag camera or subject movement that appears inconsistent, unstable, or purposeless for human review.

### 16. Generative Defect Report

Produce a timestamped report of suspected warping, flicker, identity change, object appearance, or text mutation without claiming automatic creative approval.

## P1 — Salvage and continuity

### 17. `kino body-swap`

Replace the video beneath an approved audio track while stream-copying and verifying the audio.

### 18. `kino salvage-clip`

Create safe derivatives: clean-prefix trim, clean-suffix trim, freeze-frame extension, still extraction, defect-region crop, or background-only derivative.

### 19. Continuity Assistant

Compare adjacent clips for subject identity, screen direction, motion direction, scale, lighting, color, framing, and cut compatibility.

### 20. Approved Clip Reuse

Locate previously approved clips that satisfy a semantic beat before requesting another generation.

### 21. Protected Timeline Regions

Lock approved portions of a sequence so rerenders operate only on selected shots or stages.

### 22. Resume-Aware Rendering

Reuse verified completed stages and rerender only changed or failed operations.

## P1 — Audio continuity

### 23. `kino audio-bed`

Provide one-shot music-under-voice composition with bed looping, crossfades, voice-driven ducking, fades, loudness normalization, and exact duration policy.

### 24. `kino bed-audition`

Create one labeled reel that auditions several music beds beneath the real voice track.

### 25. `kino voice-style-check`

Detect segment-level discontinuities in loudness, pace, pitch, cadence, and silence spacing.

### 26. `kino voice-identity-check`

Compare speaker embeddings across segments and against an approved reference voice.

### 27. ASR Timestamp Clamp

Clamp transcription segment boundaries to the actual audio duration before calculating pace or style metrics.

### 28. Audio Preservation Verification

Verify that operations intended to preserve approved audio produced packet-identical or stream-identical audio.

### 29. Audio Duration Safety

Prevent audio operations from silently shortening the video. Require an explicit shortest-stream policy.

### 30. Audio Seam Report

Produce timestamped style, identity, loudness, and edit-boundary findings for human listening.

## P1 — Text and subtitle reliability

### 31. ASS Subtitle Support

Accept `.ass` subtitle files while preserving explicit styling, positioning, and PlayRes settings.

### 32. Dimension-Aware SRT and VTT Rendering

Derive subtitle layout from real video dimensions instead of unsuitable libass defaults.

### 33. Subtitle Safe-Area Check

Detect captions outside platform-safe regions or underneath common interface overlays.

### 34. Subtitle Temporal QA

Detect missing lines, overlaps, excessive reading speed, unexpected gaps, and captions extending beyond EOF.

### 35. Deterministic Graphics Layer

Add important text, labels, captions, and logos during editing instead of trusting generated imagery to reproduce them.

## P2 — Asset intelligence

### 36. `kino clip-index`

Maintain a local registry containing stable clip ID, semantic beats, prompt and provenance, source hash, technical properties, QA verdict, known defects, approved trim ranges, and usage history.

### 37. Semantic Clip Search

Search approved assets using concepts such as decision moment, product close-up, owner label, or calm establishing shot.

### 38. Generation Lineage

Link each take to its source image, references, prompt, model, settings, variants, trims, repairs, and final uses.

### 39. Duplicate and Near-Duplicate Detection

Detect identical or visually similar takes before generating, downloading, or reviewing more footage.

### 40. Prompt Outcome Memory

Record which prompts, models, references, and settings produced approved or rejected results.

### 41. Reusable Bed Registry

Track approved music beds, mood, tempo, usage restrictions, audition history, and previous approvals.

## P2 — Editorial planning

### 42. Semantic Beat Map

Define the purpose of each planned shot and connect timeline clips to the beats they satisfy.

### 43. Coverage Report

Show which required beats have approved footage, weak footage, rejected footage, or no footage.

### 44. Regeneration Decision Assistant

Compare the likely cost of trimming, repairing, masking, replacing, or regenerating a take.

### 45. Continuity Plan

Establish subject, geography, screen direction, scale, lighting, and motion expectations across planned shots.

### 46. Variant-Aware Timeline

Preserve shared editorial decisions while supporting vertical, square, horizontal, and platform-specific variants.

## P2 — Review and approval

### 47. AI-Video Review Package

Produce a standard bundle containing the final candidate, motion strips, text-region crops, audio seam report, technical QA, receipt, known limitations, and human-review checklist.

### 48. Timestamped Review Decisions

Record approve, reject, trim, repair, or regenerate decisions against exact clip ranges.

### 49. Human Review Gate

Prevent a video from being marked publishable until required review artifacts have explicit human approval.

### 50. Known-Limitation Ledger

Preserve intentionally accepted defects so later agents do not repeatedly rediscover or fix them.

### 51. Approval Invalidation

Automatically invalidate approval when a protected source, hash, timing, subtitle, mix, or render parameter changes.

## P2 — CLI and agent ergonomics

### 52. Namespaced CLI

Organize commands beneath `kino inspect`, `kino edit`, `kino audio`, `kino captions`, `kino qa`, `kino assets`, and `kino workflow`. Preserve flat commands as compatibility aliases.

### 53. Agent-Mode Output

Default to structured JSON or plain line-oriented output when stdout is not a TTY.

### 54. Capability Discovery

Let agents query available tools, optional dependencies, supported formats, and unavailable capabilities without parsing full help output.

### 55. Recommended Next Action

Return one bounded next step after a failed preflight, QA gate, missing capability, or incomplete review.

### 56. `kino doctor --migrations`

Detect stale MCP registrations, retired package names, outdated environments, dead executable paths, and legacy assembler workflows.

## P3 — Learning production system

### 57. Project Learning Report

Summarize accepted and rejected takes, frequent defect classes, successful prompts, reused assets, regeneration costs, and repeated manual workarounds.

### 58. Defect-to-Prompt Feedback

Translate repeated editing defects into generation constraints and prompt recommendations.

### 59. Workflow Recipe Capture

Save a successful editing sequence as a reusable, versioned recipe with inputs, policies, checks, and review gates.

### 60. Production Cost Ledger

Track generations, rejected takes, trims, repairs, manual review, render time, and reuse savings.

### 61. Acceptance Benchmark

Replay representative fixtures against new Kinocut versions to detect regressions in duration, subtitles, audio preservation, QA artifacts, and receipts.

## Design principles

- AI footage is temporally uncertain; inspect motion and late frames, not only stills.
- Approved elements must be machine-protected and hash-verifiable.
- Automated checks produce evidence and findings, not unsupported claims about taste.
- Human review remains mandatory for creative acceptance and publication.
- Every important output should be traceable to its sources and transformations.
- Every completed project should improve future prompting, generation, reuse, and review.
- Existing flat CLI, MCP, and Python interfaces remain compatible while deeper workflows become namespaced and receipt-backed.

---

# Copy-paste implementation prompt

```text
Continue Kinocut by turning the approved AI-video editor feature backlog into a decision-complete, implementation-ready roadmap and then executing it in dependency-safe phases.

Canonical artifact:
- KINOCUT_AI_VIDEO_EDITOR_FEATURE_BACKLOG.md

Source of truth:
- Verify the live canonical Kinocut repository, Forgejo remote, current master, open issues, active PRs, and dirty-worktree boundaries before changing anything.
- Do not assume a similarly named local checkout is canonical.

Objective:
Implement the backlog's 61 proposed capabilities without breaking Kinocut's existing MCP, Python, CLI, workflow, receipt, security, or compatibility surfaces.

Product doctrine:
- Traditional editing assumes footage is evidence; AI-generated footage is a proposal requiring adjudication.
- Kinocut's durable workflow is: specify -> ingest -> inspect -> classify -> salvage or regenerate -> assemble -> verify -> review -> register what worked.
- Automated analysis creates review evidence. It never claims creative taste has passed.
- Human review remains mandatory before publication.

First actions:
1. Read the complete backlog and inspect the current implementation before designing changes.
2. Search for existing utilities and partially overlapping tools before proposing anything new.
3. Map every backlog item to one of: already exists, extend existing, new primitive, composition of existing primitives, optional capability, or defer with a concrete dependency.
4. Produce a coverage matrix for all 61 items with current evidence and proposed ownership.
5. Decompose the work into independently testable subprojects and ordered PR waves.
6. Write explicit public contracts for receipts, asset IDs, clip verdicts, review artifacts, approvals, invalidation, and capability reporting before implementation.

Recommended implementation order:
1. Core acceptance, ingest, provenance, preflight, verdict, defect, locking, and receipt contracts.
2. Temporal inspection and generative-defect review artifacts.
3. Salvage, body-swap, approved-element preservation, continuity, and resume-aware rendering.
4. Audio duration safety, audio-bed, bed audition, voice style, voice identity, and audio verification.
5. ASS/SRT/VTT reliability, safe areas, temporal subtitle QA, and deterministic graphics.
6. Clip index, semantic retrieval, lineage, duplicate detection, prompt outcome memory, and bed registry.
7. Beat maps, coverage, regeneration decisions, continuity planning, and variant-aware timelines.
8. Review packages, timestamped decisions, human gates, limitation ledgers, and approval invalidation.
9. Namespaced CLI, agent-mode output, capability discovery, next-action guidance, and migration doctor.
10. Learning reports, defect-to-prompt feedback, recipe capture, cost ledger, and acceptance benchmarks.

Engineering constraints:
- Use isolated worktrees. Preserve unrelated dirty work.
- Follow strict TDD: prove each regression test fails before implementation, then make it pass.
- Reuse existing validation, FFmpeg execution, escaping, defaults, limits, custom errors, receipt, and workflow utilities.
- Escape every user-controlled FFmpeg filter value.
- Use custom Kinocut error types and bounded subprocess calls.
- Keep files and functions within repository size limits.
- Maintain MCP, CLI, and Python parity for public capabilities.
- Preserve existing flat commands as compatibility aliases when adding namespaces.
- Keep optional ML dependencies capability-gated; core editing must remain lightweight.
- Never expose private paths, credentials, prompts, or internal environment details in receipts, logs, docs, commits, issues, or PRs.

Quality gates:
- Focused unit and real-FFmpeg integration tests for every feature.
- Receipt privacy and hash-integrity tests.
- Temporal fixtures containing late text drift, warped motion, frozen frames, broken loops, and subtitle edge cases.
- Audio fixtures for duration mismatch, stream-copy identity, stitched loudness seams, speaker-identity seams, and ASR timestamps beyond EOF.
- MCP, CLI, and Python parity tests.
- Backward-compatibility tests for existing flat commands and result shapes.
- Full repository suite, lint, import smoke, packaging, and supported FFmpeg matrix before merge.
- Fresh independent code and security review for every PR wave.

Delivery rules:
- Build and merge in small, dependency-ordered PRs with one coherent change unit each.
- Attach sanitized verification receipts to the relevant Forgejo issues.
- Do not version-bump, tag, publish packages, submit directories, deploy, or create a release unless the user explicitly authorizes that separately after reviewing the completed implementation.
- Stop before release and provide a final coverage matrix, test receipts, remaining limitations, and human-review checklist.

Begin by reporting the verified live repository state and producing the 61-item current-state coverage matrix. Do not start implementation until the architecture, contracts, PR waves, and acceptance tests are decision-complete.
```
