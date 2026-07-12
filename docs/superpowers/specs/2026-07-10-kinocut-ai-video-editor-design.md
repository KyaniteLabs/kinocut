# Kinocut AI-Video Editor: Contract-First Program Design

**Date:** 2026-07-10
**Status:** approved direction; written-spec review required before implementation
**Coverage input:** `2026-07-10-kinocut-ai-video-backlog-coverage.md`
**Field evidence input:** `2026-07-10-kinocut-field-wishlist-design.md`
**Release state:** implementation may proceed after written-spec review; release remains separately forbidden

## 1. Decision

Implement the 61-item AI-video backlog as a contract-first program over Kinocut's shipped engines, workflow receipts, resume mechanism, semantic timeline/index, rescue verifier, quality checks, and compatibility surfaces.

Do not implement 61 unrelated commands and do not wait for a kernel rewrite before fixing field-proven safety defects. Shared contracts land first; the audio-duration and subtitle-bypass defects follow immediately; higher-order commands are governed compositions over the shared records and existing engines. Durable protected timeline regions and changed-revision render reuse integrate with the planned kernel rather than creating a second project/revision system.

The product loop is:

```text
acceptance spec
  -> content-addressed ingest
  -> deterministic preflight and inspection evidence
  -> explicit verdict and defects
  -> protected salvage or regeneration decision
  -> receipt-backed assembly
  -> deterministic and optional QA findings
  -> hash-bound human review
  -> approved asset, prompt, cost, and recipe learning
```

Automated checks may report measurements, confidence, and findings. They never assert that creative taste passed. Only a human review decision can move an artifact to `publishable`.

## 2. Alternatives considered

### A. One command per backlog item

Rejected. It would duplicate storage, provenance, approval, and capability logic across dozens of tools and make invalidation unreliable.

### B. Contract-first hybrid over shipped engines — chosen

Land a small record model, then deliver safety fixes and compositional workflows in dependency order. This reuses the current product and gives each PR a testable outcome.

### C. Kernel-first rewrite

Rejected as the primary sequence. It would delay the proven add-audio and subtitle defects and risk building a competing workflow/resume system. Kernel work is used only where durable revisions are actually required.

## 3. System boundaries

### 3.1 Canonical state versus derived state

Canonical project state consists only of versioned records:

- acceptance specs and beat/continuity requirements;
- immutable asset records and generation lineage;
- clip verdicts, defect findings, protected elements, and limitations;
- review decisions and approval states;
- prompt outcomes, usage events, costs, and recipes.

Indexes, coverage reports, review packages, learning reports, recommendations, and benchmark summaries are derived and rebuildable. They cannot silently become independent sources of truth.

### 3.2 Project layout

A Kinocut AI-video project uses a caller-selected project directory and a private state directory beneath it:

```text
project/
  kinocut.project.json
  .kinocut/
    assets/sha256/<digest>/<sanitized-name>
    records/<record-kind>.jsonl
    receipts/<receipt-id>.json
    artifacts/<artifact-kind>/<artifact-id>/...
    indexes/<index-kind>.json
    locks/
```

Rules:

- Ingest copies bytes into the content-addressed asset store before normalization or repair.
- The source digest is computed from bytes and is the stable identity; filenames are labels only.
- Canonical records are append-only. Corrections supersede prior records by ID; they do not rewrite history.
- Indexes and reports can be deleted and rebuilt from canonical records.
- Writes use a project lock and atomic temporary-file replacement. A failed write leaves the last valid record intact.
- Public receipts contain project-relative paths, IDs, and hashes only. They never contain home paths, usernames, prompts by default, credentials, or environment dumps.
- Raw prompts and usage-rights evidence are private project records. Public exports expose opt-in summaries or hashes.

Cross-project reuse is explicit rather than ambient. A caller may configure a local library directory containing signed/snapshotted approved `AssetRecord`, verdict, rights, beat, and usage projections from selected projects. Publishing a record to the library is a human-authorized action; Kinocut never scans unrelated directories automatically. The originating project records remain canonical, library entries retain their origin record IDs and hashes, and stale/missing origins are reported rather than silently treated as current approval.

### 3.3 Compatibility

- Existing MCP tool names, Python client methods, flat CLI commands, argument defaults, and result fields remain valid.
- New fields are additive. Existing receipt readers continue to accept older receipt kinds and versions.
- New namespaced CLI commands call the same handlers as compatibility aliases; they do not create divergent behavior.
- Public capabilities maintain MCP, Python, and CLI parity unless explicitly classified as an internal record API.
- Optional ML dependencies fail soft with a typed `capability_unavailable` finding. Deterministic inspection and human review remain usable.

## 4. Public contracts

All contracts are strict, versioned Pydantic models with canonical JSON serialization. Unknown fields fail validation when writing canonical records. Readers may support documented older versions through explicit migrations.

### 4.1 Common identity and provenance

Every canonical record includes:

```text
schema_version
record_kind
record_id                 # sha256 of canonical semantic content
project_id
created_at                # informational; excluded from semantic ID
created_by                # human | agent | tool identifier, sanitized
supersedes                # optional prior record ID
source_record_ids[]
```

`project_id` is the cryptographically random, durable identity stored in the
private `.kinocut/project.json` metadata record. It is never inferred from a
directory name. Append, read, and public-operation boundaries require an exact
match with the opened store identity; initialized legacy stores without identity
metadata fail closed rather than guessing an identity.

Media identities use `asset_id = sha256:<64 lowercase hex>`, computed from original bytes. Derived artifacts have their own byte hash plus a semantic artifact record ID.

### 4.2 `GenerationAcceptanceSpec`

Required fields:

- `spec_id`, title, target formats, and review policy;
- required subjects, actions, semantic beats, exact text, logos, and visual rules;
- forbidden defect codes and per-code severity thresholds;
- required evidence artifacts and required human-review roles;
- optional continuity plan reference and cost ceiling.

Exact text is stored privately by default. Public receipts contain its hash and declared region, not the text, unless explicitly exported.

### 4.3 `AssetRecord` and `GenerationLineage`

`AssetRecord` contains:

- `asset_id`, media kind, project-relative original location, byte size, ingest time;
- technical preflight summary and preflight artifact ID;
- usage-rights status and private evidence reference;
- model/provider identifiers, prompt hash, generation settings hash, source/reference asset IDs;
- parent/variant relationships and derived artifact IDs.

Ingest is idempotent by digest. Re-ingesting identical bytes returns the existing asset and records an optional observation event; it does not duplicate the original.

### 4.4 `ClipVerdict`

The only editorial dispositions are:

```text
approved
approved_with_trim
background_only
repairable
still_frame_salvage
rejected
regenerate
```

A verdict binds the exact asset hash, optional approved range, acceptance-spec ID, reviewer, rationale, defect IDs, and review-decision ID. `approved_with_trim` requires a non-empty bounded range. Rejected and regenerate records cannot enter an approved-only search result.

### 4.5 `DefectFinding`

Required fields:

- stable defect code and taxonomy version;
- asset/artifact ID and exact time range;
- optional normalized spatial region;
- severity, confidence, detector/provenance, measurements, and evidence artifact IDs;
- `status = suspected | confirmed | accepted_limitation | resolved | false_positive`;
- human decision reference when status is not `suspected`.

The initial stable taxonomy includes text drift, identity drift, object mutation, warping, flicker, unwanted camera motion, continuity failure, late-frame degradation, frozen frames, black frames, corrupt frames, broken loop, subtitle overflow, subtitle timing, audio duration, audio style seam, and voice identity seam.

### 4.6 `ProtectedElement`

A protected element binds:

- element type: source asset, audio stream, clip range, timeline range, graphic, subtitle set, timing map, mix, or render parameter set;
- exact dependency fingerprint;
- allowed operations and explicit duration policy;
- human approval reference.

Every mutating operation computes its touched dependency set before rendering. A collision with a protected element fails with `protected_element_change` unless a new explicit human review decision authorizes the change. There is no force flag for agents.

### 4.7 Receipt extension

Existing receipt kinds remain valid. AI-video fields are added in a nested, additive `ai_video` section rather than changing legacy top-level meanings:

```json
{
  "ai_video": {
    "contract_version": 1,
    "project_id": "...",
    "acceptance_spec_id": "...",
    "ordered_inputs": [],
    "transformations": [],
    "duration_policy": {},
    "preservation_proofs": [],
    "finding_ids": [],
    "review_artifact_ids": [],
    "approval_state_id": "...",
    "warnings": []
  }
}
```

Each ordered input includes asset ID, input hash, in/out points, probed duration, and role. Each transformation includes tool/op name, sanitized parameters or parameter hash, toolchain versions, output duration, output hash, and warnings. Preservation proofs state what was expected to remain identical, comparison method, source/output fingerprints, and verdict.

### 4.8 `InspectionPackage` and `ReviewPackage`

`InspectionPackage` is a manifest referencing technical metadata, preview, muted preview, motion strip, sampled frames, declared-region crops, frame-difference measurements, and findings. Missing optional analyzers are listed as unavailable capabilities, never silently omitted.

`ReviewPackage` references the final candidate, inspection artifacts, audio seam report, subtitle QA, technical QA, receipt, known limitations, required checklist, and approval state. Manifests are deterministic for the same referenced artifacts; media encoding bytes are not claimed deterministic across FFmpeg builds.

### 4.9 `ReviewDecision`, `KnownLimitation`, and `ApprovalState`

`ReviewDecision` records the actor as human, decision (`approve`, `reject`, `trim`, `repair`, `regenerate`, or `accept_limitation`), exact target/range, rationale, and dependency fingerprint. Acceptance approvals also bind the exact acceptance-spec record, review role, explicit per-requirement coverage IDs, and evidence bindings from required evidence key to content-addressed artifact ID. An approved verdict is valid only while that exact human decision is an active leaf; acceptance is derived from the union of active, exact decision evidence and never from a blanket verdict label.

`ApprovalState` contains:

- candidate artifact and full dependency fingerprint;
- required artifact IDs and their integrity results;
- required human decisions;
- `state = pending | approved | invalidated | rejected`;
- invalidation reasons and superseding state ID.

Any protected source hash, timing, subtitle, graphics, mix, render parameter, required artifact, or accepted-limitation change produces a different fingerprint. Prior approval remains historical but becomes inapplicable; the new candidate starts `pending`.

`publishable` is a derived result, never a mutable boolean: candidate integrity passes, required artifacts exist and re-hash, no blocking finding is unresolved, and the current dependency fingerprint has the required human approval.

### 4.10 `CapabilityReport` and `NextAction`

`CapabilityReport` is stable structured data containing public capability ID, surface availability, supported formats, required and optional dependencies, availability state, unavailability reason code, and remediation text. It never requires parsing CLI help.

Failures and incomplete reports may include exactly one `next_action`:

```text
action_code
summary
command_template          # optional, sanitized, never executed automatically
blocking_record_ids[]
```

Next actions are bounded remediation suggestions, not agent autonomy grants.

### 4.11 Learning records

- `PromptOutcome`: prompt hash/private reference, model/settings, asset IDs, verdicts, defects, and final-use events.
- `UsageEvent`: approved asset/bed usage, project/beat, output receipt, and timestamp.
- `CostEvent`: category, quantity, unit, optional currency, source, and confidence. Unknown cost is explicit; it is never inferred as zero.
- `WorkflowRecipe`: versioned workflow spec template, typed parameter slots, policies, required checks, and review gates.

Learning and cost reports are deterministic projections over these records. Model-generated prose may summarize but cannot alter them.

## 5. Feature behavior decisions

### 5.1 Safety defaults

- `video_add_audio` defaults to preserving video duration. Audio is padded, looped, or trimmed only according to an explicit policy.
- Shortest-stream behavior requires the explicit `shortest` policy and always emits a duration-change warning.
- Body swap defaults to preserving approved audio and rejecting a video-duration mismatch. `pad_video`, `trim_video`, or `trim_audio` must be explicit.
- Audio-preserving operations compare packet/stream fingerprints and fail the preservation gate if the declared guarantee is not met.
- ASR segments are clamped to real EOF before pace, cadence, silence, or seam metrics are calculated; the clamp is recorded as a warning/finding.

### 5.2 Temporal evidence

- Motion strips sample across the full playable duration and include late/final frames.
- Default temporal percentages are 0, 25, 50, 75, 95, and the last decodable frame; callers may supply a bounded alternative.
- Declared text/logo regions are normalized coordinates, extracted at source resolution, and accompanied by the sampled timestamp.
- Deterministic checks cover black/frozen/duplicate/corrupt segments, loop endpoints, frame differences, subtitle timing, and technical properties.
- Motion intent, identity/object mutation, visual continuity, speaker identity, and near-duplicate analysis are optional evidence providers.

### 5.3 Salvage and reuse

- Salvage never overwrites an original. Every derivative has lineage, operation policy, output hash, and a fresh verdict.
- Approved clip reuse searches only verdict-compatible, rights-compatible records and returns why each result matched.
- Regeneration recommendations remain advisory and display evidence, estimated cost range, missing data, and alternatives.

### 5.4 Audio bed and audition

- Audio bed owns the one-shot policy: exact target duration, loop seams/crossfades, voice-driven ducking, fades, loudness target, true-peak ceiling, and receipt.
- Bed audition uses the same ship-level mix policy as final composition, labels equal-duration candidates, and never updates bed approval automatically.

### 5.5 Subtitle and graphics reliability

- ASS input preserves authored styles, positions, and PlayRes.
- SRT/VTT are converted through dimension-aware ASS using actual display dimensions.
- Subtitle QA reports overlap, reading speed, gaps, EOF overflow, and safe-area/overlay collisions.
- Important exact text and logos are deterministic editor layers, never trusted to generated pixels.

## 6. Dependency-ordered PR waves

Each PR is one coherent change unit, starts from current master in its own worktree, follows red-green-refactor TDD, runs the full suite, receives independent code/security review, merges, and deletes its branch/worktree before the next dependent wave starts.

### Wave 0 — Contract foundation

**PR 0.1: canonical AI-video records and private project store**

- Contracts: acceptance, asset, lineage, verdict, defect taxonomy/finding, protected element, review decision/state, limitation, learning events.
- Atomic append-only project store, content-addressed asset path rules, migrations, privacy serialization.
- No new editing behavior and no public command explosion.
- Covers foundations for #1–8, #36–45, #48–51, #57–60.

**PR 0.2: receipt and capability contracts**

- Additive `ai_video` receipt section, preservation proofs, capability report, and next-action model.
- Backward-reader fixtures for every existing receipt kind.
- Covers #8, #28, #47, #51, #54–55.

### Wave 1 — Immediate field safety

These PRs can proceed in parallel after 0.2 because they own disjoint engines.

**PR 1.1: loss-proof add-audio**

- Duration policies, keep-video default, shortest warning, receipt evidence.
- MCP/CLI/Python parity and real-FFmpeg regression for the eaten-outro defect.
- Covers #29 and part of #8/#28.

**PR 1.2: ASS and dimension-aware subtitle burn**

- ASS preservation, SRT/VTT conversion using real display dimensions, EOF clamp shared utility.
- Real vertical-video and authored-ASS fixtures.
- Covers #27, #31–32.

### Wave 2 — Ingest and deterministic inspection

**PR 2.1: ingest, immutable originals, and unified preflight**

- Project creation/ingest, stable IDs, generation metadata, rights status, technical/loudness/integrity report.
- Covers #2–4 and supplies #36/#38.

**PR 2.2: temporal evidence package**

- Motion strip, late-frame sampler, text-region crops, temporal-inspect manifest.
- Covers #9–12.

**PR 2.3: deterministic temporal defect checks**

- Loop integrity and black/frozen/duplicate/corrupt interval findings.
- Covers #13–14 and deterministic parts of #16.

**PR 2.4: optional visual findings providers**

- Capability-gated motion-intent and generative-defect analyzers over the same inspection artifacts.
- Findings remain suspected evidence until a human decision; provider absence leaves the deterministic package complete.
- Covers #15–16.

### Wave 3 — Verdict, protection, and salvage

**PR 3.1: editorial verdict and defect workflow**

- Public verdict/taxonomy APIs, acceptance-spec evaluation report, protected-element mutation precheck.
- Covers #1, #5–7.

**PR 3.2: body swap and audio preservation proof**

- Explicit duration policy, approved-audio preservation, packet/stream fingerprint verifier.
- Covers #17 and #28.

**PR 3.3: salvage derivatives**

- Clean prefix/suffix, freeze extension, still, region crop, and background-only derivatives with lineage.
- Covers #18.

### Wave 4 — Audio continuity

**PR 4.1: one-shot audio bed and audition**

- Shared mix policy, looping/crossfade/duck/fade/normalize/exact duration; audition reel recipe.
- Covers #23–24 and #41 integration seam.

**PR 4.2: voice seam metrics and report**

- EOF clamp, deterministic loudness/pace/silence metrics, optional pitch/cadence and speaker embeddings, aggregate report.
- Covers #25–27 and #30.

### Wave 5 — Subtitle and graphics QA

**PR 5.1: subtitle temporal and safe-area QA**

- Cue overlap/gap/reading-speed/EOF checks, platform-safe profiles, full-resolution samples.
- Covers #33–34.

**PR 5.2: deterministic graphics recipe**

- Receipt-bound text/logo/caption composition over existing engines.
- Covers #35.

### Wave 6 — Asset intelligence

**PR 6.1: approved clip and bed registries**

- Persistent `ClipRecord` and bed subtype, usage history, exact duplicate detection.
- Covers #20, #36, #38, #41.

**PR 6.2: semantic and near-duplicate retrieval**

- Existing semantic index over approved records; optional embeddings/perceptual fingerprints.
- Covers #37 and #39.

**PR 6.3: prompt outcome memory**

- Private prompt references/hashes linked to verdicts, defects, variants, and final uses.
- Covers #40.

### Wave 7 — Editorial planning and continuity

**PR 7.1: beat map, coverage, and continuity plan**

- Planned beats, clip bindings, deterministic coverage report, declared inter-shot expectations.
- Covers #42–43 and #45.

**PR 7.2: continuity evidence and regeneration advice**

- Deterministic adjacent-clip metrics, optional identity/VLM evidence, cost-aware repair/regenerate comparison.
- Covers #19 and #44; #44 remains unavailable until enough cost/outcome data exists.

**PR 7.3: variant contract integration**

- Carry shared beats, protected elements, approvals, and lineage through shipped workflow variants.
- Completes #46 without replacing existing variants.

### Wave 8 — Review and approval

**PR 8.1: review package and timestamped decisions**

- Standard manifest, integrity checks, exact-range decisions, known-limitations ledger.
- Covers #47–48 and #50.

**PR 8.2: human gate and approval invalidation**

- Dependency fingerprints, fail-closed publishability derivation, invalidation reasons.
- Covers #49 and #51.

### Wave 9 — CLI and agent ergonomics

**PR 9.1: namespaced CLI and non-TTY output policy**

- `kino inspect|edit|audio|captions|qa|assets|workflow`; flat aliases preserved; central JSON/line policy.
- Covers #52–53.

**PR 9.2: capabilities, next action, and migration doctor**

- Stable capability output, one bounded recommendation, stale registration/package/path/workflow diagnostics.
- Covers #54–56.

### Wave 10 — Learning and regression system

**PR 10.1: recipe, cost, and learning reports**

- Versioned recipe capture, cost events, project learning aggregation, evidence-backed defect-to-prompt rules.
- Covers #57–60; #58 remains advisory and unavailable when evidence is insufficient.

**PR 10.2: AI-video acceptance benchmark**

- Versioned synthetic/redistributable fixtures, expected findings, receipt/invalidation/duration/subtitle/audio-preservation checks, cross-version result manifest.
- Covers #61.

### Kernel integration wave — explicitly gated

**PR K.1: protected timeline regions and changed-stage reuse**

- Compile protected ranges into durable project revisions and extend shipped hash-resume into changed-revision DAG reuse.
- Covers #21 and completes #22.
- Starts only after the existing kernel gate is explicitly reconciled by a human. No parallel project/revision store is permitted.

## 7. Parallelization and ownership

After Wave 0 merges:

- Wave 1.1 owns audio-add engine/surfaces/tests.
- Wave 1.2 owns subtitle engine/surfaces/tests.
- Wave 2.1 owns project-store ingest/preflight.
- Wave 2.2 owns inspection artifact composition.

These may run concurrently in isolated worktrees. Later parallel-safe pairs are 3.2/3.3, 4.1/5.1, 6.2/6.3, and 9.1/9.2 after their shared contracts land. Receipt schema, public-surface manifests, shared defaults, and central capability registry are controller-owned merge points; workers do not edit them concurrently without an assigned integration slice.

## 8. Acceptance and test strategy

### Every PR

- Write the failing regression/contract test first and capture the red result.
- Unit tests for strict validation, canonical hashes, migrations, privacy, and typed errors.
- Real-FFmpeg integration tests for media behavior; mocks only for unavailable external/ML providers.
- MCP call, Python client, CLI handler, and public-surface parity for each public feature.
- Backward fixtures for flat CLI aliases and legacy result/receipt shapes.
- `python3 -m pytest tests/ -x -q --tb=short`.
- `python3 -c "import kinocut"`.
- Ruff/type checks required by current CI.
- Public leak audit before commit, issue receipt, push, or PR.
- Independent author/reviewer roles; author does not self-approve.

### Required fixture families

- Audio shorter/longer than video, silent source, multiple streams, stream-copy preservation, loudness and speaker seams, ASR past EOF.
- Vertical/horizontal/square SRT/VTT/ASS, authored positions/PlayRes, safe-area collisions, overlaps, gaps, reading-speed and EOF failures.
- Late text drift, broken loop, warped motion, black/frozen/duplicate/corrupt intervals, identity/object change evidence.
- Identical and perceptually similar clips, conflicting rights/verdicts, prompt variants, usage history.
- Approval invalidation by each protected dependency class.
- Interrupted workflows, tampered intermediates, changed specs/revisions, and variant isolation.

### Program completion gate

The program is implementation-complete only when all 61 rows have a merged owner or an explicitly exercised unavailable/deferred contract; the final coverage matrix links every item to code, tests, and receipts; the full supported FFmpeg/platform matrix is green; and an independent review package is approved by a human.

## 9. Error and failure behavior

- Canonical records fail closed on unknown fields, invalid hashes, missing lineage, out-of-range times, or stale approval fingerprints.
- Media operations raise Kinocut custom errors; FFmpeg stderr remains bounded through existing processing helpers.
- Optional analyzers return typed unavailable capability entries and do not block deterministic artifact generation unless the acceptance spec explicitly requires them.
- Partial package generation writes no “complete” manifest. Resume verifies every reused artifact hash.
- Recommendation and learning surfaces disclose missing evidence and confidence. They never manufacture cost, rights, approval, or creative-quality facts.

## 10. Release boundary

Implementation, test commits, issue receipts, and dependency-ordered PRs are authorized only after written-spec review. The following remain separately prohibited:

- version bump;
- git tag or release branch;
- package upload;
- MCP/directory submission;
- deployment;
- release creation or announcement.

After the final implementation wave, stop and provide the final coverage matrix, test and leak-audit receipts, known limitations, optional/deferred capability state, and human-review checklist. Wait for explicit release authorization.

## 11. Supersession

This design expands the narrower `2026-07-10-kinocut-field-wishlist-design.md`. That document remains authoritative for the detailed field evidence behind its 12 items where it does not conflict with this program design. This document owns the shared contracts, full 61-item dependency graph, PR waves, and program completion gate.
