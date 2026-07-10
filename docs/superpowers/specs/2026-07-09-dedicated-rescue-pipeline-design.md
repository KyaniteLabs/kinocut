# MCP Video Dedicated Rescue Pipeline Design

> **Historical design record:** This document preserves the package name and
> source paths used when the rescue pipeline was designed. The project is now
> Kinocut; use `kinocut`, `kino`, and the current documentation for new work.

**Status:** Approved for implementation planning

**Date:** 2026-07-09

**Target release:** MCP Video 1.6.x follow-up

## Summary

MCP Video will add a first-class, local-only rescue pipeline for the ordinary-person request: **"Fix this clip."** The flagship input is a flawed talking-head recording from a phone or webcam. The pipeline diagnoses defects, separates safe repairs from uncertain suggestions, creates review artifacts, applies only explicitly approved work, verifies that content was preserved, and packages outputs with a machine-readable receipt.

The rescue pipeline is restoration infrastructure, not a creative editor. Its defining promise is trustworthy improvement without silently changing what happened or what was said.

## Product Decisions

The design is governed by these approved decisions:

1. **Trust ladder:** invisible technical repair is the baseline; diagnose-and-propose is the default experience; publish-ready creative autopilot is a later explicit mode.
2. **Flagship job:** rescue one flawed clip before expanding into montage creation or long-form repurposing.
3. **Timeline preservation:** every recorded moment and its order are sacred in rescue mode. No automatic trimming, silence removal, filler removal, retake selection, or reordering.
4. **Confidence policy:** uncertain repairs are not applied. Abstaining with an explanation is a successful result.
5. **Generative boundary:** restorative local AI is allowed, but the system may not invent words, events, people, objects, or identity details.
6. **Canonical input:** a talking-head phone or webcam recording with realistic audio, lighting, framing, orientation, and compatibility defects.
7. **Captions:** generate editable captions and a transcript automatically; never burn captions into the repaired video without approval.
8. **Default package:** emit a repaired master, universal sharing copy, captions, transcript, and receipt.
9. **Privacy:** media never leaves the machine. Cloud fallback is prohibited.
10. **Responsiveness:** target a diagnosis, preview set, and runtime estimate within approximately 30 seconds on named benchmark hardware. Full rendering may take longer.

## Problem

MCP Video exposes many capable editing operations, but a non-editor or calling agent must still know which tools to combine, in what order, and which changes are safe. That creates four failure modes:

- technically valid media can still be hard to hear, poorly oriented, dim, unstable, or incompatible with common players;
- agents can apply individually reasonable operations that conflict or damage the result;
- uncertainty is expressed inconsistently, encouraging best-effort guesses instead of safe abstention;
- outputs lack one unified restoration plan that explains what will change, what will not change, and why.

Consumer tools have made captions, noise cleanup, loudness correction, orientation fixes, enhancement, compatible export, and undo or revert behavior feel routine. MCP Video's opportunity is to provide those expectations through a local, inspectable, agent-safe contract rather than an opaque one-click transformation.

## Goals

- Provide one coherent rescue workflow across MCP, CLI, and Python.
- Diagnose common talking-head defects without rendering the full clip.
- Classify every proposed action with evidence, confidence, and policy disposition.
- Preserve the source, timeline, event order, stream continuity, and spoken meaning.
- Reuse existing MCP Video engines and workflow infrastructure where they satisfy the contract.
- Make every output reproducible and inspectable through hashes, parameters, measurements, and verification results.
- Fail closed when a repair is uncertain, unavailable locally, stale, or policy-incompatible.
- Leave clean state after cancellation or failure.

## Non-Goals

The first rescue release does not implement:

- transcript-based editing, silence removal, filler removal, or pacing changes;
- montage creation, best-take selection, auto B-roll, music selection, or beat cutting;
- subject-aware reframing or stabilization that silently discards meaningful image regions;
- eye-contact correction, voice cloning, background generation, or background replacement;
- cloud rendering, cloud AI, remote storage, semantic search, hosting, or delivery;
- a creative publish-ready autopilot;
- a replacement for the generic workflow engine.

These may become separate designs built on the rescue plan and receipt contracts.

## User Experience

### 1. Diagnose

The user or agent calls `rescue-plan` with one input clip and an output directory. The command performs bounded probing and sampled analysis, then returns:

- detected defects and supporting measurements;
- safe repairs;
- recommendations that require explicit approval or another workflow;
- unavailable local capabilities;
- policy-blocked actions;
- representative preview artifacts;
- estimated render time and relevant hardware information.

No media is modified during diagnosis.

### 2. Approve

The user or agent reviews the plan. Safe repairs are eligible for execution but are not rendered merely because planning succeeded. Timeline-preserving recommendations may be explicitly promoted when the plan marks them as promotable. Timeline-changing or synthetic-content actions cannot be promoted under the `local_content_preserving` policy.

### 3. Render

The renderer validates the plan, source hash, policy, local dependencies, output confinement, and approval set. It writes to an isolated temporary job directory and promotes outputs only after verification succeeds.

### 4. Inspect

The inspection surface summarizes status, repairs, skipped work, before-and-after measurements, verification results, output integrity, privacy, and provenance without modifying media.

## Public API

The three surfaces must ship together.

| Stage | MCP tool | CLI command | Python client |
|---|---|---|---|
| Diagnose | `video_rescue_plan` | `rescue-plan` | `Client.rescue_plan()` |
| Execute | `video_rescue_render` | `rescue-render` | `Client.rescue_render()` |
| Review | `video_rescue_inspect` | `rescue-inspect` | `Client.rescue_inspect()` |

The initial release intentionally omits a one-command `rescue` wrapper. Keeping plan and render explicit prevents agents from collapsing the approval boundary. A future wrapper may compose these operations without changing their contracts.

## Architecture

### Rescue Analyzer

The analyzer owns read-only probing and sampled measurements. It should reuse existing probe, technical quality, design quality, audio, caption, and workflow helpers rather than reimplementing their logic.

Responsibilities:

- validate the input and enumerate streams;
- capture source identity and hashes;
- detect defects and collect evidence;
- estimate confidence independently for each proposed repair;
- select representative preview timestamps;
- identify required local executors and models;
- estimate render cost against named hardware;
- emit a deterministic plan for identical inputs, configuration, and available dependencies.

### Rescue Policy Engine

The policy engine is the sole authority for automatic eligibility. Detection code may describe a defect, but it may not decide that a repair is safe to execute.

The initial policy is `local_content_preserving` and enforces:

- local execution only;
- immutable source files;
- preserved timeline and event order;
- preserved source streams unless the plan explicitly adds a derived stream;
- no synthetic speech, events, people, objects, or identity details;
- explicit availability and confidence;
- no silent fallback to a different repair or backend;
- no output promotion before verification.

### Rescue Plan

The plan is a versioned, machine-readable artifact bound to the source and policy. It is suitable for human review, agent approval, replay, and staleness checks.

Each finding has one disposition:

- `safe_repair`: high-confidence and policy-compatible;
- `recommendation`: plausible improvement that requires approval or a separate editing workflow;
- `unavailable`: cannot run with the currently available local dependencies or hardware;
- `blocked`: violates a hard rescue policy and cannot be promoted.

### Rescue Renderer

The renderer compiles approved plan actions into existing vetted engine operations. It must not accept arbitrary raw FFmpeg fragments from the plan. New restoration engines are introduced only when the existing engine surface cannot satisfy an approved repair contract.

The renderer owns:

- plan and source revalidation;
- dependency pinning and executor selection;
- temporary job workspace creation;
- bounded execution, progress, cancellation, and cleanup;
- intermediate hashes and operation receipts;
- handoff to verification and package promotion.

### Rescue Verifier and Packager

The verifier independently checks the rendered artifacts. It must not infer success from the renderer's exit code alone.

The packager emits:

- repaired master;
- universal H.264/AAC MP4 sharing copy;
- caption sidecar;
- plain transcript;
- rescue receipt;
- previews and before-and-after measurements;
- skipped recommendations with reasons.

The repaired master preserves the source dimensions, frame rate, and stream structure wherever they are valid and compatible with the approved repairs. The sharing copy is a derived compatibility artifact and does not replace the master. The master and sharing copy are required for a successful video rescue. Captions and the transcript are generated when a compatible local speech-to-text capability is available; otherwise the package manifest records those artifacts as unavailable without failing unrelated repairs.

## Plan Schema

The concrete schema may add fields during implementation, but these semantics are required:

```json
{
  "schema_version": 1,
  "receipt_kind": "rescue_plan",
  "tool": "video_rescue_plan",
  "status": "planned",
  "source": {
    "path": "input/talking-head.mov",
    "sha256": "source-sha256",
    "size_bytes": 123456,
    "streams": []
  },
  "policy": {
    "id": "local_content_preserving",
    "version": 1,
    "local_only": true,
    "timeline_locked": true
  },
  "findings": [],
  "safe_repairs": [],
  "recommendations": [],
  "unavailable_repairs": [],
  "blocked_repairs": [],
  "preview_artifacts": [],
  "estimate": {
    "seconds": 0,
    "hardware": {},
    "confidence": "low"
  },
  "plan_sha256": "plan-sha256"
}
```

Every proposed repair includes:

- stable repair ID and repair type;
- evidence and before measurement;
- confidence score and confidence rationale;
- policy disposition;
- exact bounded parameters;
- expected benefit and known tradeoffs;
- required executor or local model;
- whether it is promotable;
- preview artifact references when useful.

Stored paths follow the existing receipt privacy policy: workspace-relative where possible, never public home-directory paths or credentials.

## Render Receipt

The render receipt uses `receipt_kind: "rescue"` and records:

- source and plan hashes;
- approved repair IDs;
- exact operations and parameters;
- MCP Video, FFmpeg, model, and executor versions;
- intermediate and final output hashes;
- before-and-after measurements;
- verification checks and their explicit units;
- skipped, unavailable, and blocked repairs;
- progress, cancellation, failure, resume, and cleanup state;
- privacy statement confirming local-only execution;
- package manifest.

Receipt inspection follows the additive schema policy used by existing workflow receipts. Known fields remain readable when future schema versions add new fields.

## Repair Catalog

### Safe Automatic Candidates

The policy may classify these as safe only when evidence and repair-specific thresholds pass:

- rotation and display-aspect correction;
- timestamp and container repair;
- metadata normalization;
- stream-preserving universal MP4 export;
- conservative speech loudness normalization;
- clipping prevention that does not conceal unrecoverable clipping;
- high-confidence local speech denoising;
- conservative exposure and white-balance correction;
- caption sidecar and transcript generation.

There is no single global confidence threshold. Each repair type defines calibrated evidence, minimum confidence, contraindications, and verification checks. Policy tests prove that lowering one repair's threshold cannot weaken another repair's gate.

### Recommendation-Only Candidates

- stabilization requiring material crop;
- subject-aware crop or reframe;
- deblur, upscale, or damaged-frame reconstruction;
- aggressive color or HDR reconstruction;
- background cleanup;
- burned captions or visual caption styling;
- silence, filler, false-start, retake, or pacing edits.

Timeline-changing recommendations are informational under the initial policy and must be performed through a separately approved editing workflow.

### Always Blocked In Rescue Mode

- cloud upload or remote processing;
- invented or cloned speech;
- generated events, people, objects, or identity details;
- silent timeline cuts or reordering;
- overwriting the source;
- unconfined output writes;
- execution from a stale or altered plan.

## Data Flow

1. Validate and hash the source.
2. Probe streams, timing, codecs, metadata, and decodability.
3. Run bounded sampled analyzers.
4. Normalize analyzer results into findings with explicit metrics and units.
5. Evaluate each finding through the rescue policy.
6. Generate preview artifacts and the runtime estimate.
7. Serialize and hash the rescue plan.
8. On render, revalidate the source, plan, policy, approvals, dependencies, and output root.
9. Compile approved repairs to vetted engine calls.
10. Render into an isolated job workspace with progress and cancellation support.
11. Verify preservation and quality independently.
12. Atomically promote the package or quarantine the failed result.
13. Write the final receipt and cleanup manifest.

## Failure, Cancellation, And Resume

- Invalid input fails before plan creation with a structured error code.
- A missing local model produces `unavailable`, not an installation side effect or cloud fallback.
- An altered source produces `rescue_source_mismatch`.
- An altered or stale plan produces `rescue_plan_mismatch`.
- A policy violation produces `rescue_policy_violation`.
- A renderer timeout or cancellation records the completed stages and leaves no promoted package.
- Verification failure produces a quarantined receipt with the failing checks and artifact locations.
- Resume is allowed only when the source hash, plan hash, policy, executor versions, and completed intermediate hashes still match.
- Cancellation and failed experiments must clean temporary processes and artifacts that are not required for diagnosis or resume.

## Verification Contract

Verification covers both success and failure paths:

- source is unchanged;
- output decodes from start to finish;
- timeline duration remains within a codec-aware tolerance of the source;
- frame and packet timestamps are monotonic;
- no source stream disappears silently;
- audio and video remain synchronized;
- captions remain synchronized and uncertain words are surfaced;
- spoken-content coverage does not regress beyond a documented tolerance;
- universal MP4 meets its declared codec, pixel format, audio, and metadata contract;
- each reported metric includes its definition and unit;
- no failed verification can coexist with a successful package status;
- output and receipt hashes match persisted artifacts;
- receipt content passes the public leak audit.

## Test Strategy

### Unit And Contract Tests

- schema validation and additive-reader compatibility;
- repair-specific confidence and contraindication policies;
- local-only enforcement and missing-model behavior;
- source, plan, policy, and intermediate staleness checks;
- CLI, MCP, and Python argument and result parity;
- structured error codes and exit semantics;
- receipt privacy and output confinement.

### Integration Fixtures

The committed or reproducibly generated fixture matrix includes:

- shaky portrait phone recording;
- dim webcam footage;
- wind, hum, echo, clipping, and quiet speech;
- wrong rotation and malformed timestamps;
- variable frame rate and audio drift;
- unusual but supported containers and codecs;
- missing local models and unsupported hardware;
- interrupted and resumed renders;
- a repair that improves one metric while damaging another;
- hostile filenames, Unicode, long paths, and corrupted input.

### End-To-End Gates

- plan generation is read-only;
- safe-only rendering preserves the timeline;
- recommendation promotion is explicit and receipt-backed;
- failed verification quarantines outputs;
- cancellation leaves clean state;
- repeated runs are deterministic within documented codec tolerances;
- focused suites, the complete relevant suite, and the FFmpeg compatibility matrix pass;
- adversarial UltraQA covers malformed input, stale plans, dirty worktrees, bounded timeouts, misleading success output, and cleanup.

## Performance And Hardware Reporting

The approximately 30-second diagnosis goal is a measured target, not an unconditional promise. Benchmark reports name:

- CPU, GPU, memory, and operating system;
- clip duration, resolution, codecs, and stream count;
- enabled analyzers and local models;
- cold-start and warm-start times;
- sampling strategy;
- estimate accuracy versus actual render time.

When the target cannot be met, the planner returns the available partial diagnosis, identifies deferred analyzers, and reports an honest revised estimate. It must not silently skip a required safety check to meet the target.

## Compatibility And Migration

- Existing MCP tools, CLI commands, Python methods, workflows, and receipts remain valid.
- Rescue operations are additive.
- The rescue renderer consumes existing vetted engine calls rather than changing their public behavior.
- Optional local restoration dependencies remain optional and discoverable through `doctor`.
- The universal sharing copy is an additional output and never replaces the repaired master.
- The intentional 24 fps quality behavior remains unchanged.

## Research Basis

Current official product documentation supports the table-stakes assumptions behind the design:

- CapCut documents [automatic captions](https://www.capcut.com/tools/add-subtitles-to-video), [loudness normalization](https://www.capcut.com/tools/loudness-normalization), and [Auto Cut](https://www.capcut.com/help/how-to-use-auto-cut).
- Descript documents [filler-word removal](https://help.descript.com/hc/en-us/articles/10164806394509-Remove-filler-words), [word-gap shortening](https://help.descript.com/hc/en-us/articles/10164807277453-Shorten-word-gaps), [audio ducking](https://help.descript.com/hc/en-us/articles/10327507829773-Lower-audio-of-other-layers), and [version history](https://help.descript.com/hc/en-us/articles/10164106619405-Version-history).
- Google Photos documents [video enhancement and stabilization](https://support.google.com/photos/answer/10729480?co=GENIE.Platform%3DAndroid&hl=en), while Apple Photos documents [trim with revert](https://support.apple.com/en-us/104968).
- Creatomate documents browser [live preview](https://creatomate.com/docs/api/preview-sdk/what-is-the-preview-sdk) and [version history](https://creatomate.com/docs/fundamentals/template-editor/version-history); Remotion documents [parameterized rendering](https://www.remotion.dev/docs/parameterized-rendering) and [visual editing](https://www.remotion.dev/docs/visual-editing).

The market generally separates creation, semantic understanding, rendering, and delivery. MCP Video should not reproduce every cloud platform. Its differentiated role is a vendor-neutral, local `plan -> approve -> render -> verify -> package` contract with strong provenance and safe abstention.

## Acceptance Criteria

The design is complete when implementation can demonstrate all of the following:

1. A valid talking-head clip produces a versioned plan without modifying the source.
2. Every finding has evidence, explicit metrics and units, confidence, and one policy disposition.
3. Only approved, policy-compatible repairs execute.
4. No timeline-changing or synthetic-content operation can execute under the initial policy.
5. Missing local capabilities are reported without network access or implicit installation.
6. Successful rendering produces the required master and sharing copy, all available derived artifacts, an explicit unavailable-artifact manifest, and a valid receipt.
7. Source, plan, policy, and resume mismatches fail closed with stable error codes.
8. Verification failures quarantine outputs and return nonzero CLI status.
9. Cancellation and retries preserve the source and clean temporary state.
10. MCP, CLI, and Python surfaces have behavioral parity.
11. The fixture corpus, relevant full suite, FFmpeg matrix, privacy audit, and adversarial QA pass.
12. Diagnosis performance is reported against named hardware with estimate-versus-actual evidence.

## Follow-On Designs

The rescue contract intentionally becomes the foundation for later, independently approved work:

1. subject-aware reframe and advanced stabilization;
2. transcript-driven timeline editing;
3. publish-ready creative autopilot;
4. multi-asset auto composition;
5. semantic clip understanding and retrieval;
6. optional cloud render, delivery, and hosting adapters.

Each follow-on must define its own trust boundary instead of weakening `local_content_preserving` rescue mode.
