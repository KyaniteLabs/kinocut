# Kinocut AI-Video Backlog: Verified Current-State Coverage

**Date:** 2026-07-10
**Status:** design input; no implementation or release authorization
**Canonical repository:** `KyaniteLabs/kinocut` on Forgejo
**Verified master:** `fdbf3483004a8bfd3a1b3c959fdbd1c89dc90bdc`

## BLUF

The 61-item backlog is not 61 greenfield features. Current master contains a mature path-based editor, workflow receipts and hash-checked resume, variants, semantic timeline/index contracts, exact-EDL approvals, rescue verification, technical/design quality checks, and broad MCP/CLI/Python surfaces. It does not yet contain the durable asset, verdict, defect, protected-region, review-decision, or learning ledgers that make the proposed AI-video loop coherent.

Current classification:

| Classification | Count | Meaning |
|---|---:|---|
| Already exists | 1 | Substantial public behavior exists; only integration/documentation work remains. |
| Extend existing | 28 | A shipped primitive or contract is the correct owner but lacks required fields or policy. |
| New primitive | 13 | No trustworthy current owner exists. |
| Composition | 10 | Implement as a governed recipe/package over existing primitives, not another low-level engine. |
| Optional capability | 6 | Core must work without ML; richer analysis is capability-gated and evidence-only. |
| Defer | 3 | Requires an explicit upstream contract/data source before implementation is safe. |

Fresh Epoch sizing for the whole program: optimistic 180h, most likely 320h, pessimistic 520h; PERT expected 330h, 95% interval 216.67–443.33h. This supersedes the narrower 12-item estimate.

## Repository snapshot at initial design time

- Forgejo `origin/master` and `git ls-remote` agree on `fdbf348` (merged PR #127, native MCPB foundation).
- This section records the initial design baseline and is not current implementation status.
- Issue #126 remains open as the 12-item field-feedback ledger and explicitly authorizes no release.
- The 61-item backlog expands and supersedes the implementation scope of the narrower field-wishlist design; that design remains useful as a detailed first slice.
- Baseline verification at design time was 2,230 passed and 15 skipped. Implementation has since started; use the [current draft status](../../status/2026-07-12-wishlist-draft-pr-status.md) and an exact-SHA verification receipt for present state.

## Classification key

- **AE** — already exists
- **EE** — extend existing
- **NP** — new primitive
- **CO** — composition of existing primitives
- **OC** — optional capability, fail-soft and evidence-only
- **DF** — defer behind named dependency

## 61-item coverage matrix

| # | Capability | Class | Current evidence | Proposed owner / dependency |
|---:|---|:---:|---|---|
| 1 | Generation Acceptance Spec | NP | Workflow specs validate execution graphs, not creative acceptance (`kinocut/workflow/spec.py`, `validator.py`). | `kinocut/contracts/acceptance.py`; project manifest schema. |
| 2 | AI Asset Ingest | EE | `video_project_create`, workflow sources, and semantic `SourceEvidence` exist, but generation metadata/rights do not (`server_tools_creation.py`, `semantic/models.py`). | Extend source/asset contract; kernel `media_ingest` later supplies durable storage. |
| 3 | Immutable Source Preservation | EE | Workflow planning/rendering hashes sources and never mutates inputs; no immutable asset store exists (`workflow/planner.py`, `executor.py`). | Asset store + content-addressed original; reuse receipt hash/privacy utilities. |
| 4 | Media Preflight | EE | `video_info`, probe, quality guardrails, and loudness checks cover much of the technical data separately (`server_tools_basic.py`, `engine_probe.py`, `quality_guardrails.py`). | One preflight report composed over canonical probes; add integrity/color/audio fields. |
| 5 | Explicit Clip Verdicts | NP | “verdict” currently means workflow validation, not editorial disposition. | Strict `ClipVerdict` model bound to asset hash and optional trim range. |
| 6 | Defect Taxonomy | NP | Quality/rescue checks emit heterogeneous codes; no canonical generative-defect vocabulary. | Versioned taxonomy shared by inspection, verdicts, review, and learning. |
| 7 | Approved-Element Locking | NP | Semantic EDL approval binds exact hashes, but media/timeline elements cannot be locked generally (`semantic/edl.py`). | `ProtectedElement` contract + mutation guard; later compile into kernel revisions. |
| 8 | Receipt-Backed Editing | EE | Workflow and layer receipts already carry source/input/output hashes, steps, versions, warnings, resume cursor, and privacy rules (`workflow/executor.py`, `docs/VIDEO_RECEIPT.md`). | Add ordered clip timing, transformations, duration policy, preservation proofs, review bindings. |
| 9 | Motion Strip | CO | `video_storyboard`, `video_thumbnail`, and frame export exist (`server_tools_media.py`, `engine_storyboard.py`, `engine_frames.py`). | Deterministic tiled recipe with sampling policy and receipt artifact. |
| 10 | Late-Frame QA | CO | Arbitrary thumbnail/frame extraction and storyboard sampling exist; no mandated 0/50/75/95/100 policy. | Inspection sampler recipe + findings schema. |
| 11 | Text-Drift Check | CO | Frame extraction, crop, and text/layout guardrails exist; no temporal declared-region package. | Compose full-resolution sampled crops; optional OCR only enriches findings. |
| 12 | Temporal Inspect | CO | Preview, storyboard, frame extraction, probe, and quality checks exist independently. | Standard inspection bundle manifest and artifact directory. |
| 13 | Loop Integrity Check | NP | Reverse and comparison tools exist, but no first/last-state loop metric or finding. | Deterministic opening/closing frame-difference analyzer with thresholds. |
| 14 | Frozen/Black/Corrupt Detection | EE | Quality guardrails already measure temporal motion and probe integrity, but lack bounded segment reporting (`quality_guardrails.py`). | Extend technical QA with black/freeze/duplicate/unreadable intervals. |
| 15 | Motion Intent Check | OC | Visual-intelligence models expose camera motion and ambiguity, not creative intent (`visual_intelligence/analysis.py`). | Metric baseline plus optional VLM rubric; always return evidence for human review. |
| 16 | Generative Defect Report | OC | Rescue/quality findings exist but do not detect identity/object/text mutation as one report. | Aggregate deterministic checks; optional vision model proposes timestamped findings. |
| 17 | Body Swap | NP | Timeline editing and audio extraction exist; no public replace-video/verify-audio primitive. | New engine primitive with explicit pad/trim/reject policy and preservation proof. |
| 18 | Salvage Clip | EE | Trim, crop, thumbnail/frame export, and rescue planning exist; freeze extension/background-only policy are missing. | Extend rescue operations and expose one derivative-producing composition. |
| 19 | Continuity Assistant | OC | Visual intelligence measures tracks, landmarks, framing, motion, and crop continuity; no adjacent-clip rubric. | Deterministic metrics plus optional embeddings/VLM findings. |
| 20 | Approved Clip Reuse | EE | Dependency-free semantic timeline/index and query already exist (`semantic/index.py`). | Query the approved clip registry, filtered by verdict and rights. |
| 21 | Protected Timeline Regions | DF | Current timelines are one-shot; durable revision/timeline kernel is planned but blocked post-release (`docs/plans/2026-07-09-kinocut-trusted-execution-layer.md`). | Depends on durable project/revision mutation guards; define contract now, implement with kernel. |
| 22 | Resume-Aware Rendering | EE | Workflow render resumes completed steps only when spec/input/output hashes still match (`workflow/executor.py`, `docs/WORKFLOWS.md`). | Extend from same-spec failure resume to revision/DAG changed-stage reuse in kernel. |
| 23 | Audio Bed | EE | `audio_compose` supports tracks, volume, offsets, and looping; `video_duck_audio` supports sidechain ducking (`server_tools_audio.py`). | One governed facade adds crossfade, fades, normalization, exact duration policy, receipt. |
| 24 | Bed Audition | CO | Audio compose/duck, timeline text labels, and merge exist. | Recipe generating labeled equal-length sections under the real voice. |
| 25 | Voice Style Check | OC | Loudness analysis exists; pace/pitch/cadence/silence seam comparison does not. | Core metric plugin set; optional pitch/ASR dependencies capability-gated. |
| 26 | Voice Identity Check | OC | No speaker-embedding comparison surface exists. | Optional local embedding provider with approved-reference and per-segment scores. |
| 27 | ASR Timestamp Clamp | EE | Transcription and subtitle verification parse timed segments; EOF policy is not centralized (`ai_engine/transcribe.py`, `rescue/verifier.py`). | Canonical timing clamp used before every derived metric. |
| 28 | Audio Preservation Verification | EE | Rescue verifier probes packets/streams and continuity; no declared packet/stream identity contract (`rescue/verifier.py`). | Add source/output audio fingerprints and policy-specific verdict. |
| 29 | Audio Duration Safety | EE | `video_add_audio` exposes no duration policy and can inherit shortest-stream behavior (`server_tools_basic.py`, `engine_audio_ops.py`). | Default keep-video policy, explicit shortest option, mismatch warnings, receipt fields. |
| 30 | Audio Seam Report | CO | Loudness/quality data, transcription, and planned style/identity checks can share one report. | Composition over #25–29; no separate analyzer stack. |
| 31 | ASS Subtitle Support | EE | Public subtitle tool documents SRT/VTT only (`server_tools_media.py`, `engine_subtitles.py`). | Extend validated subtitle formats; preserve ASS styles/position/PlayRes. |
| 32 | Dimension-Aware SRT/VTT Rendering | EE | Subtitle burn exists but relies on current libass defaults. | Probe display dimensions and synthesize safe ASS render settings. |
| 33 | Subtitle Safe-Area Check | NP | General text-layout guardrails exist, but no subtitle cue/platform-overlay analysis. | Subtitle layout sampler + platform-safe-area profiles. |
| 34 | Subtitle Temporal QA | EE | Subtitle parsing/EOF verification exists in rescue verifier; generated subtitle timing already has tests. | Add overlap, gap, reading-speed, missing-line, and EOF findings. |
| 35 | Deterministic Graphics Layer | CO | Text, animated text, styled subtitles, watermark, overlays, and compositor already exist. | Prescribed graphics recipe bound to source assets/fonts and receipt hashes. |
| 36 | Clip Index | EE | Semantic index has stable source/span IDs, hashes, deterministic querying, and provenance; it is not a persistent approved-asset registry. | Persist versioned `ClipRecord` over asset/verdict/defect/usage contracts. |
| 37 | Semantic Clip Search | EE | `video_semantic_query` and dependency-free local semantic index already ship (`server_tools_postrescue.py`, `semantic/index.py`). | Index clip beats/tags/approved ranges; optional embeddings remain additive. |
| 38 | Generation Lineage | EE | Workflow receipts and semantic evidence carry provenance/hashes but not generation families. | Extend asset lineage graph across references, prompt, model, variants, repairs, final uses. |
| 39 | Duplicate/Near-Duplicate Detection | OC | Exact hashes detect duplicates; no perceptual similarity index. | Exact match in core; optional perceptual/video embedding provider for near-duplicates. |
| 40 | Prompt Outcome Memory | NP | Prompt provenance is not linked to verdict outcomes. | Local append-only outcome records built from asset lineage + verdict. |
| 41 | Reusable Bed Registry | NP | No music-bed registry or approval/history schema exists. | Asset subtype registry with rights, mood, tempo, audition and approval history. |
| 42 | Semantic Beat Map | EE | Semantic timeline spans and deterministic EDL already model source meaning, not planned-shot requirements. | Add planned `BeatRequirement` and clip-to-beat satisfaction bindings. |
| 43 | Coverage Report | CO | Becomes a deterministic projection of acceptance spec, beat map, clip verdicts, and index. | Read-only report; no new storage model. |
| 44 | Regeneration Decision Assistant | DF | No calibrated repair/generation cost ledger or outcome corpus exists. | Depend on #40, #57, and #60; start rules-based and label estimates explicitly. |
| 45 | Continuity Plan | NP | Visual continuity metrics exist but there is no declarative inter-shot expectation contract. | `ContinuityPlan` bound to beat/shot IDs; assistant compares evidence to plan. |
| 46 | Variant-Aware Timeline | AE | Workflow variants reuse sources/steps and apply bounded overrides, producing separate receipts (`workflow/variants.py`, `docs/WORKFLOWS.md`). | Integrate approval/beat/asset contracts; retain current compatibility. |
| 47 | AI-Video Review Package | CO | Workflow inspector returns integrity, human-review pointers, and known limitations; preview/storyboard/QA/receipts exist separately. | Standard package manifest assembling #9–16, #30, receipt and checklist. |
| 48 | Timestamped Review Decisions | EE | `EditApproval` binds exact EDL/edit IDs; rescue render has explicit approval. Neither models range verdicts generally. | General `ReviewDecision` with asset/timeline hash, exact range, actor, rationale. |
| 49 | Human Review Gate | EE | Release checkpoint and workflow inspector surface human-review state; no durable publishable transition. | Fail-closed gate requiring named artifacts and explicit human decision. |
| 50 | Known-Limitation Ledger | EE | Workflow inspector emits static known limitations, not project-accepted findings (`workflow/inspector.py`). | Append-only accepted-limitation records bound to finding and artifact hash. |
| 51 | Approval Invalidation | EE | EDL approvals and workflow resume already fail on hash mismatch (`semantic/edl.py`, `workflow/executor.py`). | General dependency fingerprint for sources, timings, subtitles, mix, params, and render. |
| 52 | Namespaced CLI | NP | Current parser exposes a large flat command set; no namespace router. | Add namespace aliases over identical handlers; preserve all flat commands. |
| 53 | Agent-Mode Output | EE | CLI supports structured formatting/JSON flags but does not uniformly switch on non-TTY. | Central output policy in `cli/runner.py`; explicit flag always overrides auto mode. |
| 54 | Capability Discovery | EE | `search_tools` returns names/descriptions/required params; doctor reports optional dependency readiness. | One stable capability document covering tools, formats, dependencies and reasons unavailable. |
| 55 | Recommended Next Action | NP | Errors and workflow warnings sometimes include suggestions, but no typed cross-surface contract. | Optional `next_action` field with bounded enum/template; never execute automatically. |
| 56 | Doctor Migrations | EE | `doctor` probes executables/packages and rescue readiness; migration hygiene is absent (`doctor.py`). | Add read-only registrations/package/env/path/workflow checks and remediation text. |
| 57 | Project Learning Report | CO | All inputs will exist across verdict, defect, lineage, usage, cost, and review ledgers. | Deterministic aggregate report, not another source of truth. |
| 58 | Defect-to-Prompt Feedback | DF | Requires canonical defects and enough linked prompt outcomes to avoid unsupported advice. | Depend on #6, #40, #57; rule-based evidence first, optional model wording second. |
| 59 | Workflow Recipe Capture | EE | Versioned workflow specs already encode inputs, operations, variants, resume and receipts. | Add parameter slots, acceptance/review requirements, provenance and recipe registry. |
| 60 | Production Cost Ledger | NP | Render durations and workflow activity exist only incidentally; generation/review/reuse costs are not modeled. | Append-only project events with units and provenance; derived totals only. |
| 61 | Acceptance Benchmark | EE | Confidence benchmark and broad golden/real-FFmpeg/workflow fixtures already verify receipts and review artifacts (`docs/VIDEO_RECEIPT.md`, `tests/test_workflow_golden.py`). | Expand to versioned AI-video fixture corpus and cross-version result manifest. |

## Architectural conclusion

The coherent implementation unit is not each command. It is a small set of shared contracts and ledgers:

1. **Project intent:** acceptance spec, beats, continuity plan.
2. **Asset truth:** immutable asset identity, generation lineage, rights, verdicts, defects.
3. **Protection:** protected elements/regions and generalized approval fingerprints.
4. **Evidence:** inspection artifacts, QA findings, audio/subtitle preservation proofs.
5. **Decision:** timestamped human review, limitations, publishability gate.
6. **Learning:** outcome, cost, recipe, and benchmark records derived from the above.

Commands such as motion-strip, temporal-inspect, bed-audition, coverage-report, review-package, and learning-report should be compositions over those contracts. ML-based motion intent, generative defect, continuity, voice identity, and perceptual duplicate analysis must remain optional enrichments; deterministic evidence and human review stay available without them.

## Stop condition

This document is current-state analysis only. Before implementation, the public contracts, storage boundaries, compatibility policy, PR waves, and acceptance tests must be approved and written into the expanded design. No version bump, tag, publish, directory submission, deployment, or release is authorized.
