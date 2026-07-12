# Kinocut all-open-loops controller audit and execution manifest

**Status:** decision-complete repo-native manifest; audit only — no implementation, push, merge, tag, publish, deploy, or release authorized by this document.

**Audit base:** `c0032d8` on `codex/niko-plan-audit` (this branch).

**Source documents used (public):**
- `AGENTS.md`
- `docs/AI_VIDEO_CONTRACTS.md`, `docs/AI_VIDEO_INSPECTION.md`, `docs/AI_VIDEO_REVIEW_AND_SALVAGE.md`
- `docs/KINOCUT-FEATURES-ROADMAP.md`, `docs/KINOCUT-AUDIO-FEATURES.md`, `docs/INTEGRATION-ROADMAP.md`
- `docs/plans/2026-07-09-kinocut-trusted-execution-layer.md`
- `docs/plans/2026-07-12-wishlist-parallel-execution.md`
- `docs/superpowers/specs/2026-07-10-kinocut-ai-video-editor-design.md`
- `docs/superpowers/specs/2026-07-10-kinocut-ai-video-backlog-coverage.md`
- `docs/superpowers/specs/2026-07-10-kinocut-field-wishlist-design.md`
- `docs/superpowers/specs/2026-07-11-kinocut-sound-sonic-world-design.md`
- `docs/superpowers/plans/2026-07-11-kinocut-ai-video-plan-index.md` plus plans 00–05
- `docs/superpowers/plans/2026-07-12-kinocut-sound-plan-index.md`
- `docs/status/2026-07-12-wishlist-draft-pr-status.md`
- `docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md`
- `docs/DIRECTORY_REBRAND_STATUS.md`, `docs/MCPB.md`, `docs/MCPB_SUPPLY_CHAIN.md`, `docs/C2PA_PROVENANCE.md`
- Public Forgejo issue trackers (#54, #55, #85, #88, #90, #126) and merged PRs (#118–#127) as referenced from the above repo docs.

**Audit method:** every claimed capability was checked against the source/test tree at `c0032d8` before being marked closed. Items marked open cite the exact file/function gap. The three current PR blockers were verified by reading `kinocut/aivideo/salvage.py`, `kinocut/aivideo/protection.py`, `kinocut/engine_body_swap.py`, and the focused tests.

**Release stop:** non-negotiable. This manifest authorizes no version bump, tag, package upload, registry submission, deployment, release creation, or announcement. It records the open-loop inventory and the order in which the controller should close it.

## 1. The three current PR blockers (G006)

The draft PR status (`docs/status/2026-07-12-wishlist-draft-pr-status.md`) and the verification receipt (`docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md`) record three evidence-integrity blockers on the Wave 3 tip. The latest code/security review verdict is REQUEST CHANGES; no merge or release is authorized.

### 1.1 Persisted mutation fingerprint and authorization references are absent from salvage lineage

- **Gap.** `kinocut/aivideo/salvage.py::create_salvage_derivative` builds a `MutationIntent` via `_mutation_intent(...)` and passes it to `assert_no_protected_collision`, but the exact `mutation_fingerprint(intent)` and the claimed `authorization_decision_ids` are **not** written into the persisted salvage-lineage manifest.
- **Evidence.** The manifest installed by `_install_manifest` (`kinocut/aivideo/salvage.py`, near line 720) contains only `schema_version`, `operation`, `policy`, `policy_hash`, `source_asset_id`, `output_hash`, and `preservation_checks`. The fields needed to re-prove authorization on read — `mutation_fingerprint` and `authorization_decision_ids` — are missing.
- **Test gap.** No test in `tests/test_aivideo_salvage.py` asserts that the manifest records the exact fingerprint or the authorization references that were live at render time. `_read_prior_derivative` re-derives intent from `policy_hash` only, so a persisted derivative can be re-validated even if its authorization has since been superseded.
- **Owner.** Wave 3 salvage owner (`kinocut/aivideo/salvage.py`).
- **Acceptance gate.**
  1. Extend the salvage-lineage manifest schema (bump `schema_version`; add a read migration) to include `mutation_fingerprint` and `authorization_decision_ids`.
  2. `_read_prior_derivative` must reject any persisted manifest whose recomputed fingerprint differs from the stored value, or whose authorization references are no longer active and human-bound to that fingerprint.
  3. New focused tests: tamper/forgery/replay scenarios must fail closed; idempotent re-runs must still match; manifest schema migration must remain read-compatible with the prior version.
  4. Privacy: authorization IDs are record IDs (already `sha256:` digests); no host paths, prose, or credentials enter the manifest.

### 1.2 `trim_audio` body-swap proof does not bind to the declared trim of the approved source

- **Gap.** `kinocut/engine_body_swap.py::_proof` records `expected="approved_audio_trimmed"` and a `changed`/`preserved` verdict computed by comparing the source and output `_audio_fingerprint` values. It does **not** prove that the output audio is the declared bounded prefix of the approved source. A swap that substituted unrelated audio of the correct length would still pass the `trim_audio` path with `verdict="changed"`.
- **Evidence.** The `trim_audio` branch of `_render_args` only applies `-t <video_duration>`; `_proof` then asserts `preservation_required=False`, so no preservation gate fires. The test suite parametrizes `("trim_audio", 0.6, 1.0, "changed")` and accepts any "changed" verdict.
- **Test gap.** No test in `tests/test_body_swap.py` proves that `trim_audio` output packets are a bounded prefix of the approved source packets. The authorization-replay test only covers `pad_video` → `trim_audio` replay.
- **Owner.** Wave 3 body-swap owner (`kinocut/engine_body_swap.py`).
- **Acceptance gate.**
  1. Add a `_declared_trim_proof(source, output, *, duration_policy, expected_duration)` that verifies the output audio packet sequence is a prefix of the approved source packet sequence within the declared duration tolerance, plus a supplement confirming the trim length equals the video duration.
  2. Replace the generic `changed` verdict for `trim_audio` with `approved_audio_trimmed` and fail closed if the prefix relationship does not hold.
  3. New focused tests: substitute non-prefix audio of equal length; mismatched codec; trim from the wrong starting offset; replay `pad_video` authorization for `trim_audio` (already present).
  4. Update `docs/AI_VIDEO_REVIEW_AND_SALVAGE.md` to describe the strengthened proof.

### 1.3 Independent origin proofs for region-crop and still-frame salvage are missing (freeze and clean-edges are closed)

- **Already closed (do not redo):**
  - **freeze_extension** — `_freeze_checks` binds the source tail to every extension frame; `test_freeze_proof_binds_source_tail_and_every_extension_sample`, `test_black_padding_cannot_pass_as_freeze`, and `test_freeze_rejects_forgery_that_only_matches_old_sample_indexes` cover forgery.
  - **clean_edges** — `_clean_edges_origin_check` independently re-selects the source interval and compares frame hashes; `cd1ede6 fix(aivideo): verify clean-edge origin independently` plus `test_clean_edges_rejects_same_duration_from_wrong_source_interval` and `test_clean_edges_rejects_systematic_trim_interval_defect` cover it. `a6171c3 fix(aivideo): keep salvage sources descriptor-bound` and `eccd293 fix(aivideo): bind body-swap authorization policy` plus `8240ba8 test(aivideo): exercise descriptor-bound hostile renders` close the descriptor-bound hostile-render loop.
  - **background_only** — `_background_origin_check` independently crops three source frames and compares; `test_background_rejects_same_dimensions_from_wrong_origin` covers it.
- **Open — region-crop origin.** `REGION_CROP` in `_checks` only emits `requested_region_dimensions`; there is no independent pixel-origin proof. A same-dimension crop from the wrong region would pass.
- **Open — still-frame origin.** The default branch emits only `still_frame_created` with `expected="decodable_image"` and `passed=output.width > 0`. There is no proof that the still was extracted from the declared `policy["timestamp"]` of the approved source.
- **Owner.** Wave 3 salvage owner (`kinocut/aivideo/salvage.py`).
- **Acceptance gate.**
  1. Add `_region_crop_origin_check(source, output, region)` modeled on `_background_origin_check`, sampling at least three representative timestamps and comparing declared-region source hashes to output hashes; add a `test_region_crop_rejects_same_dimensions_from_wrong_origin` hostile test.
  2. Add `_still_frame_origin_check(source, output, timestamp)` that re-extracts the source frame at the declared timestamp and compares image bytes/hash; add a `test_still_frame_rejects_wrong_timestamp_or_substitute_image` hostile test.
  3. Extend `_checks` so both recipes require the new origin check; re-run the full preservation suite on every recipe.

### 1.4 Wave 3 PR unblock sequence

Close 1.1 → 1.2 → 1.3 in that order (mutation/authorization binding is the deepest contract; trim proof is engine-local; origin proofs are recipe-local). Each unit lands as one TDD commit on a Wave 3 follow-up branch off `c0032d8`. After all three close, the controller reruns the full gate (§7) on the new tip and requests a fresh independent security/architecture review before describing the draft PR as merge-ready.

## 2. Closed versus open items (program inventory)

Closed = shipped on `c0032d8` with focused tests. Open = unimplemented, partially implemented, or blocked behind a named gate. "Partial" marks a contract that exists but is missing required behavior.

### 2.1 AI-video backlog (61 items from `docs/superpowers/specs/2026-07-10-kinocut-ai-video-backlog-coverage.md`)

| # | Capability | State | Evidence (closed) / Gap (open) | Owner plan / PR |
|---:|---|:--:|---|:--:|
| 1 | Generation Acceptance Spec | closed | `kinocut/contracts/acceptance.py`, `tests/test_contracts_acceptance.py` | 00 |
| 2 | AI Asset Ingest | closed | `kinocut/aivideo/ingest.py::ingest_project_asset`, `tests/test_aivideo_ingest*.py` | 01 / PR 2.1 |
| 3 | Immutable Source Preservation | closed | `kinocut/projectstore/store.py::ingest_asset` (content-addressed, single-pass hash+copy, `O_NOFOLLOW`), `tests/test_projectstore_ingest.py` | 01 / PR 2.1 |
| 4 | Media Preflight | closed | `kinocut/aivideo/preflight.py::run_preflight`, `tests/test_aivideo_preflight.py` | 01 / PR 2.1 |
| 5 | Explicit Clip Verdicts | closed | `kinocut/aivideo/verdict.py`, `kinocut/contracts/verdict.py`, `tests/test_aivideo_verdict.py` | 02 / PR 3.1 |
| 6 | Defect Taxonomy | closed | `kinocut/contracts/defect.py`, `tests/test_contracts_defect.py` | 00 / PR 3.1 |
| 7 | Approved-Element Locking | closed | `kinocut/aivideo/protection.py::assert_no_protected_collision`, `kinocut/contracts/protection.py`, `tests/test_aivideo_protection.py`, `tests/test_contracts_protection.py` | 02 / PR 3.1 |
| 8 | Receipt-Backed Editing | partial | `AiVideoReceiptSection` + `PreservationProof` exist (`kinocut/contracts/receipt_ai_video.py`, `tests/test_receipt_ai_video.py`); body-swap and salvage receipts still need the strengthened evidence in §1.2/§1.1 | 00 / PRs 1.1, 3.2, 3.3 |
| 9 | Motion Strip | closed | `kinocut/aivideo/inspection/motion_strip.py::build_motion_strip`, `tests/test_inspection_motion_strip.py` | 01 / PR 2.2 |
| 10 | Late-Frame QA | closed | `kinocut/aivideo/inspection/samplers.py::sample_decoded_timestamps` (0/25/50/75/95/last policy), `tests/test_inspection_samplers.py` | 01 / PR 2.2 |
| 11 | Text-Drift Check | closed | `extract_region_crops`, declared-region sampler, `tests/test_inspection_samplers.py` | 01 / PR 2.2 |
| 12 | Temporal Inspect | closed | `kinocut/aivideo/surfaces.py::run_inspection_operation`, `tests/test_inspection_surfaces.py` | 01 / PR 2.2 |
| 13 | Loop Integrity Check | closed | `_text_drift_findings`/opening-closing difference in `kinocut/aivideo/inspection/temporal_checks.py`, `tests/test_inspection_temporal_checks.py` | 01 / PR 2.3 |
| 14 | Frozen/Black/Corrupt Detection | closed | `_black_findings`/`_frozen_findings`/`_corrupt_findings`, `tests/test_inspection_temporal_checks.py` | 01 / PR 2.3 |
| 15 | Motion Intent Check | closed (optional) | `analyze_optional_visual_findings` returns `provider_not_configured` deterministically; `tests/test_inspection_providers.py` | 01 / PR 2.4 |
| 16 | Generative Defect Report | closed (optional) | optional visual provider hook + deterministic findings aggregation | 01 / PRs 2.3–2.4 |
| 17 | Body Swap | partial | `kinocut/engine_body_swap.py::body_swap` ships pad/trim/reject; §1.2 trim proof still open | 02 / PR 3.2 |
| 18 | Salvage Clip | partial | `kinocut/aivideo/salvage.py::create_salvage_derivative` ships 5 recipes; §1.1 (mutation/auth persistence) and §1.3 (region-crop + still-frame origin) open | 02 / PR 3.3 |
| 19 | Continuity Assistant | open | no adjacent-clip rubric; optional VLM/embedding findings not wired | 03 / PR 7.2 |
| 20 | Approved Clip Reuse | open | semantic index exists (`kinocut/semantic/index.py`); no verdict/rights-filtered approved-clip registry query | 03 / PR 6.1 |
| 21 | Protected Timeline Regions | deferred | blocked behind kernel wave (Plan 05 / PR K.1) — contract not implemented | 05 |
| 22 | Resume-Aware Rendering | partial | workflow resume exists (`kinocut/workflow/executor.py`); revision/DAG changed-stage reuse not lifted into the kernel | 05 / PR K.1 |
| 23 | Audio Bed | open | `audio_compose`/`video_duck_audio` exist (`kinocut/server_tools_audio.py`); no governed one-shot bed facade with crossfade, fades, normalization, and exact duration policy | 02 / PR 4.1 |
| 24 | Bed Audition | open | no labeled multi-bed audition recipe | 02 / PR 4.1 |
| 25 | Voice Style Check | open | no pace/pitch/cadence/silence seam metric | 02 / PR 4.2 |
| 26 | Voice Identity Check | open | no speaker-embedding provider | 02 / PR 4.2 |
| 27 | ASR Timestamp Clamp | open | transcription parses segments (`kinocut/ai_engine/transcribe.py`) but no canonical EOF clamp before derived metrics | 01/02 / PRs 1.2, 4.2 |
| 28 | Audio Preservation Verification | partial | `_audio_evidence`/`_audio_fingerprint` exist (`kinocut/engine_body_swap.py`); §1.2 strengthens the `trim_audio` case | 02 / PR 3.2 |
| 29 | Audio Duration Safety | closed | `add_audio(..., duration_policy=...)` (`kinocut/engine_audio_ops.py`, `tests/test_add_audio_duration_policy.py`) | 01 / PR 1.1 |
| 30 | Audio Seam Report | open | composition over #25–29; no seam report | 02 / PR 4.2 |
| 31 | ASS Subtitle Support | closed | `kinocut/engine_subtitles.py`, `kinocut/subtitles_common.py`, `tests/test_subtitles_ass_and_dimension.py` | 01 / PR 1.2 |
| 32 | Dimension-Aware SRT/VTT Rendering | closed | same; `tests/test_subtitles_ass_and_dimension.py` | 01 / PR 1.2 |
| 33 | Subtitle Safe-Area Check | open | no subtitle cue/platform-overlay analyzer | 02 / PR 5.1 |
| 34 | Subtitle Temporal QA | partial | rescue verifier covers EOF (`tests/test_subtitles_eof.py`); overlap/gap/reading-speed/missing-line findings absent | 02 / PR 5.1 |
| 35 | Deterministic Graphics Layer | open | text/overlay/compositor primitives exist; no governed recipe bound to source assets/fonts and receipt hashes | 02 / PR 5.2 |
| 36 | Clip Index | open | semantic index has stable IDs; no persistent approved-asset `ClipRecord` registry | 03 / PR 6.1 |
| 37 | Semantic Clip Search | closed | `video_semantic_query`/`kinocut/semantic/index.py` | 03 / PR 6.2 (extend for clips) |
| 38 | Generation Lineage | partial | `GenerationLineage` contract + salvage lineage (`a6171c3`); cross-reference family graph not built | 03 / PR 6.1 |
| 39 | Duplicate/Near-Duplicate Detection | open | exact-hash duplicate detection only; no perceptual similarity | 03 / PR 6.2 |
| 40 | Prompt Outcome Memory | open | `PromptOutcome` contract exists (`kinocut/contracts/learning.py`); no writer/query surface | 03 / PR 6.3 |
| 41 | Reusable Bed Registry | open | no bed registry schema | 03 / PR 6.1 |
| 42 | Semantic Beat Map | open | semantic timeline spans exist; no planned `BeatRequirement` | 03 / PR 7.1 |
| 43 | Coverage Report | open | no read-only coverage projection | 03 / PR 7.1 |
| 44 | Regeneration Decision Assistant | deferred | blocked on #40, #57, #60 data | 03 / PR 7.2 |
| 45 | Continuity Plan | open | no declarative inter-shot expectation contract | 03 / PR 7.1 |
| 46 | Variant-Aware Timeline | closed | `kinocut/workflow/variants.py`, `tests/test_workflow_variants.py` | 03 / PR 7.3 |
| 47 | AI-Video Review Package | open | no standard review-package manifest assembling #9–16/#30/receipt/checklist | 04 / PR 8.1 |
| 48 | Timestamped Review Decisions | partial | `ReviewDecision` contract (`kinocut/contracts/review.py`) + Wave 3 authorization bindings exist; range-bound review decisions not exposed as a first-class surface | 04 / PR 8.1 |
| 49 | Human Review Gate | partial | `ApprovalState.is_publishable` exists (`kinocut/contracts/review.py`, `tests/test_contracts_review_blockers.py`); no durable publishable transition through the public surface | 04 / PR 8.2 |
| 50 | Known-Limitation Ledger | partial | `KnownLimitation` contract exists; no project-accepted finding write surface beyond the contract | 04 / PR 8.1 |
| 51 | Approval Invalidation | partial | `mutation_fingerprint` + `assert_no_protected_collision` cover Wave 3 mutations; generalized source/timing/subtitle/mix/render invalidation still lives only in the Wave 3 scope | 04 / PR 8.2 |
| 52 | Namespaced CLI | open | `kinocut/cli/parser/namespaces.py` planned but absent; flat commands remain the only surface (`tests/test_public_surface.py` pins 121 commands) | 04 / PR 9.1 |
| 53 | Agent-Mode Output | open | `--format json` exists; no central non-TTY auto policy in `kinocut/cli/runner.py` | 04 / PR 9.1 |
| 54 | Capability Discovery | partial | `CapabilityReport` contract exists (`kinocut/contracts/capability.py`); cross-surface capability document not assembled | 04 / PR 9.2 |
| 55 | Recommended Next Action | partial | `NextAction` contract exists; not populated by every failed gate | 04 / PR 9.2 |
| 56 | Doctor Migrations | open | `kinocut/doctor.py` probes executables; no migration/readiness checks for stale registrations, retired packages, legacy assembler workflows | 04 / PR 9.2 |
| 57 | Project Learning Report | open | derived aggregate report not built (depends on #40/#60/#6) | 04 / PR 10.1 |
| 58 | Defect-to-Prompt Feedback | deferred | blocked on #6/#40/#57 corpus | 04 / PR 10.1 |
| 59 | Workflow Recipe Capture | partial | versioned workflow specs exist; recipe registry + acceptance/review requirements absent | 04 / PR 10.1 |
| 60 | Production Cost Ledger | open | `CostEvent` contract exists; no append-only event writer or derived totals | 04 / PR 10.1 |
| 61 | Acceptance Benchmark | partial | broad golden/real-FFmpeg fixtures exist; no versioned AI-video benchmark corpus | 04 / PR 10.2 |

**Closed:** 20 of 61 (including 2 closed-optional: #15, #16). **Partial:** 15. **Open:** 23. **Deferred (kernel/data):** 3 (#21, #44, #58). The Wave 3 trio in §1 must close before any of the partial Wave 3 items (#8, #17, #18, #28) can be described as merge-ready.

### 2.2 Sound (`kinocut_sound`) program

The Sonic World audio-play program is **entirely open**. The design (`docs/superpowers/specs/2026-07-11-kinocut-sound-sonic-world-design.md`) and plan index (`docs/superpowers/plans/2026-07-12-kinocut-sound-plan-index.md`) are decision-complete; no `kinocut_sound/` module exists on this branch. All ten module-sequence leaves in the sound plan index are unstarted:

1. SoundPlan foundation contracts — open.
2. Voice providers and profiles — open.
3. Restoration/post/spatial chain — open.
4. Script parser and episode assembly — open.
5. Ambience, Foley, and world-building — open.
6. Voice consistency and roster management — open.
7. QA, metadata, loudness, true-peak, provenance — open.
8. Orchestration, cancellation/resume, caching — open.
9. Scalability and the representative benchmark — open.
10. Standalone Python/CLI plus serialized Kinocut/MCP adapters — open.

Existing bridges that will compose into sound: `kinocut/audio_engine/{core,sequencing,synthesis,spatial,stem}.py`, `kinocut/ai_engine/transcribe.py`, and `kinocut/audio_guardrails.py`. No sound-specific public CLI command or MCP tool is registered; `tests/test_public_surface.py` pins the public surface at 121 CLI commands / 142 MCP tools, none of which are sound-program commands.

### 2.3 Distribution, C2PA, and post-rescue loops

- **C2PA provenance** (PR #123, merged): `kinocut/c2pa.py` + `docs/C2PA_PROVENANCE.md`; `tests/test_c2pa_provenance.py` covers both fake-provider and real-`c2patool` paths. Treated as closed on master; no audit gap observed on this branch.
- **MCPB distribution foundation** (PR #124, merged) and **native runtime foundation** (PR #127, merged): `docs/MCPB.md`, `docs/MCPB_SUPPLY_CHAIN.md`, `server.json`, launcher contracts. Explicitly **non-publishable**; the per-platform runtime-bundling lane (clean-machine matrix, Smithery/Claude local distribution) remains open behind the standing "do not submit to Smithery or advertise as self-contained" gate.
- **Track D aggregator ledger**: `docs/DIRECTORY_REBRAND_STATUS.md` — closed for the registry-followup receipts; the Glama/roundup/publisher-refresh follow-ups are recorded as receipts.
- **GitHub mirror smoke**: present (`tests/test_public_surface.py::test_github_mirror_smoke_runs_on_master_without_private_runners`).

## 3. Dependency DAG and parallel waves

The DAG below is the controller-merged projection of `docs/superpowers/plans/2026-07-11-kinocut-ai-video-plan-index.md` §4 and `docs/plans/2026-07-12-wishlist-parallel-execution.md`. Waves already merged on this branch are marked ✓; waves with open content are marked ◻.

```text
Wave 0  ✓ canonical records + private store + receipt/capability contracts  (PRs 0.1, 0.2)
Wave 1  ✓ field safety (add-audio duration policy, ASS + dimension-aware subtitles)  (PRs 1.1, 1.2)
Wave 2  ✓ ingest + preflight + temporal inspection + optional visual findings  (PRs 2.1–2.4)
Wave 3  ◻ verdict + protection + body swap + salvage  (PRs 3.1 ✓, 3.2 partial, 3.3 partial)
            └─ §1 blockers (mutation/auth persistence, trim proof, region/still origin)
Wave 4  ◻ audio continuity (audio-bed, audition, voice style/identity, ASR clamp, seam report)
Wave 5  ◻ subtitle/graphics QA (safe-area, temporal QA, deterministic graphics)
Wave 6  ◻ asset intelligence (clip index, semantic/near-duplicate retrieval, prompt outcome, bed registry)
Wave 7  ◻ editorial planning (beat map, coverage, continuity plan/evidence, regen advice, variant integration)
Wave 8  ◻ review and approval (review package, timestamped decisions, human gate, limitation ledger, invalidation)
Wave 9  ◻ CLI/agent ergonomics (namespaced CLI, agent-mode output, capability discovery, next action, doctor migrations)
Wave 10 ◻ learning and benchmark (recipe capture, cost ledger, learning report, defect-to-prompt, acceptance benchmark)
Wave K  ◻ protected-timeline kernel — GATED behind human kernel-gate reconciliation
Sound   ◻ ten-leaf `kinocut_sound` program — foundation → voice → post/spatial → assembly → ambience →
            voice-mgmt → QA → orchestration → scalability → adapters → benchmark → Kinocut integration
```

**Hard parallelism rule** (from `docs/plans/2026-07-12-wishlist-parallel-execution.md`): at most four disjoint feature authors plus one controller/reviewer. Public-surface joins (MCP registry, CLI parser/dispatch, Python client aggregate surfaces, shared defaults/validation/limits, package exports, public-surface count tests, program ledger) are controller-serialized; one integration at a time.

**Sound program serialization:** sound work cannot be merged into the Kinocut public surface until its own foundation, voice, post/spatial, assembly, ambience, voice-management, QA, orchestration, scalability, and benchmark leaves are individually verified. The Kinocut adapter is the final serialized controller join.

## 4. Exact file ownership boundaries

These are the controller-enforced module boundaries for downstream work. An author editing outside their boundary during a wave must split the change or coordinate through the controller.

| Surface | Owner files | Public-surface test guard |
| --- | --- | --- |
| Canonical records | `kinocut/contracts/*.py`, esp. `acceptance.py`, `asset.py`, `verdict.py`, `defect.py`, `protection.py`, `review.py`, `learning.py`, `capability.py`, `receipt_ai_video.py` | `tests/test_contracts_*.py` |
| Private project store | `kinocut/projectstore/*.py` (store, layout, artifacts, migrations, ingest) | `tests/test_projectstore_*.py` |
| Ingest + inspection | `kinocut/aivideo/ingest.py`, `kinocut/aivideo/preflight.py`, `kinocut/aivideo/inspection/*.py`, `kinocut/aivideo/surfaces.py` | `tests/test_aivideo_ingest*.py`, `tests/test_aivideo_preflight.py`, `tests/test_inspection_*.py` |
| Verdict / acceptance / review | `kinocut/aivideo/verdict.py`, `kinocut/contracts/review.py` | `tests/test_aivideo_verdict.py`, `tests/test_contracts_review*.py` |
| Body swap engine | `kinocut/engine_body_swap.py` | `tests/test_body_swap.py` |
| Salvage engines | `kinocut/aivideo/salvage.py`, `kinocut/aivideo/salvage_render.py` | `tests/test_aivideo_salvage.py` |
| Mutation protection | `kinocut/aivideo/protection.py` | `tests/test_aivideo_protection.py` |
| Wave 3 public surface | `kinocut/aivideo/wave3_surfaces.py`, `kinocut/server_tools_aivideo.py`, `kinocut/cli/handlers_aivideo.py`, `kinocut/cli/parser/aivideo.py` | `tests/test_wave3_surfaces.py`, `tests/test_wave3_public_boundaries.py` |
| Field safety (audio/subtitle) | `kinocut/engine_audio_ops.py`, `kinocut/engine_subtitles.py`, `kinocut/subtitles_common.py`, `kinocut/validation.py` (BODY_SWAP_DURATION_POLICIES, etc.) | `tests/test_add_audio_*.py`, `tests/test_subtitles_*.py` |
| Source identity (snapshot/verify) | `kinocut/source_identity.py`, `kinocut/rescue/verifier.py` | `tests/test_source_identity.py`, `tests/test_g006_identity_acceptance_remediation.py` |
| Existing creative/workflow surface | `kinocut/workflow/*.py`, `kinocut/semantic/*.py`, `kinocut/creative/*.py`, `kinocut/creation_engine.py` | `tests/test_workflow_*.py`, `tests/test_creative_*.py`, `tests/test_creation_engine.py` |
| MCP registration (controller-only) | `kinocut/server_app.py`, `kinocut/server_tools_*.py`, `tests/test_public_surface.py` (`EXPECTED_SERVER_TOOLS`) | `tests/test_public_surface.py` |
| CLI parser/dispatch (controller-only) | `kinocut/cli/parser/*.py`, `kinocut/cli/handlers_*.py`, `kinocut/cli/runner.py`, `tests/test_public_surface.py` (`EXPECTED_CLI_COMMANDS`) | `tests/test_public_surface.py` |
| Python client (controller-only) | `kinocut/client/*.py` | `tests/test_client.py`, `tests/test_public_surface.py` |
| Shared defaults/validation/limits (controller-only) | `kinocut/defaults.py`, `kinocut/validation.py`, `kinocut/limits.py` | `tests/test_architecture_guardrails.py` |
| Public documentation (controller-only) | `docs/CLI_REFERENCE.md`, `docs/TOOLS.md`, `docs/PYTHON_CLIENT.md`, `docs/AI_VIDEO_*.md`, `docs/MCPB*.md`, `docs/C2PA_PROVENANCE.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `skills/kinocut/SKILL.md` | `tests/test_public_surface.py` |
| Sound program (future) | `kinocut_sound/**` (new), with adapter-only edits to `kinocut/cli/parser/*`, `kinocut/server_tools_*`, `kinocut/client/*` at integration time | to be added when foundation lands |

## 5. Integration order (controller-enforced)

1. **Wave 3 follow-ups** — close §1.1, §1.2, §1.3 as three TDD commits on a Wave 3 follow-up branch off `c0032d8`. Rerun the full gate (§7) on the new tip. Request fresh independent security/architecture review. Only then advance the draft PR state in `docs/status/2026-07-12-wishlist-draft-pr-status.md` and `docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md`.
2. **Wave 4 audio continuity** — after Wave 3 closes; PRs 4.1 (bed + audition) and 4.2 (voice style/identity + seam report + ASR clamp) can start in parallel once their contracts stabilize.
3. **Wave 5 subtitle/graphics QA** — PRs 5.1 (safe-area + temporal QA) parallel to 4.1; 5.2 (deterministic graphics) after Wave 0.
4. **Wave 6 asset intelligence** — PRs 6.1 (registries), 6.2 (semantic + near-duplicate retrieval), 6.3 (prompt outcome memory). 6.2/6.3 parallel after 6.1.
5. **Wave 7 editorial planning** — PRs 7.1 (beat map + coverage + continuity plan), 7.2 (continuity evidence + regen advice; #44 deferred on data), 7.3 (variant contract integration).
6. **Wave 8 review/approval** — PRs 8.1 (review package + timestamped decisions + limitation ledger), 8.2 (human gate + generalized approval invalidation).
7. **Wave 9 CLI/agent ergonomics** — PRs 9.1 (namespaced CLI + agent-mode output) and 9.2 (capability discovery + next action + doctor migrations) parallel after their contracts.
8. **Wave 10 learning/benchmark** — PR 10.1 (recipe + cost + learning reports) after 6.x and 8.x; PR 10.2 (acceptance benchmark) after all feature waves.
9. **Sound program** — ten-leaf sequence per §2.2; serialized Kinocut adapter is the final join.
10. **Kernel wave (gated)** — PR K.1 (protected timeline regions + stage reuse) only after explicit human kernel-gate reconciliation; the durable kernel contract named in `docs/plans/2026-07-09-kinocut-trusted-execution-layer.md` must exist first.

## 6. Per-item acceptance gates

Every closed and every open item carries the same gate shape:

1. **Contract** — strict Pydantic model under `kinocut/contracts/`; canonical `record_id` (sha256 over sorted-key compact JSON); privacy closed-bounded codes; explicit `record_kind`.
2. **Engine** — focused module under `kinocut/aivideo/`, `kinocut/engine_*.py`, or `kinocut_sound/`; uses `_escape_ffmpeg_filter_value` for every user-controlled filter value; uses custom error types from `kinocut/errors.py`; bounded subprocess timeouts via `DEFAULT_FFMPEG_TIMEOUT`; no module > 800 LOC or function > 80 lines; no dead code.
3. **Privacy** — receipts/manifests carry project-relative paths and hashes only; raw prompts, host paths, and credentials are structurally unrepresentable; the public leak audit (`scripts/git-professional-audit.sh`, `scripts/repo-readiness-audit.py`, `.github/scripts/check-forbidden-artifacts.py`) is clean.
4. **Surface parity** — MCP tool, Python client method, and flat CLI command call the same adapter; `tests/test_public_surface.py` pins the expected counts and identities.
5. **Tests** — focused unit + real-FFmpeg integration; privacy/integrity/hostility cases; idempotency and tamper-fail-closed cases; backward readers for prior receipt/record versions.
6. **Review** — independent author/reviewer roles; the author does not self-approve; final architecture + security review recorded as WATCH/REQUEST CHANGES/APPROVE with exact tip SHA.
7. **Receipts** — issue/PR receipts cite exact commit, focused/full test counts, skips/warnings, elapsed time, CI status, compatibility risks, and remaining external gates. The controller replaces task-local receipts with exact-tip receipts before describing a draft as merge-ready.

For the §1 blockers specifically:

- **§1.1 acceptance:** manifest schema bumped; persisted `mutation_fingerprint` and `authorization_decision_ids`; `_read_prior_derivative` rejects mismatched or stale-authorization manifests; three new focused tests (tamper, replay, idempotent re-run).
- **§1.2 acceptance:** `_declared_trim_proof` verifies output audio is a bounded prefix of the approved source within tolerance; `expected="approved_audio_trimmed"`; hostile-prefix tests for equal-length substitution, wrong codec, wrong offset.
- **§1.3 acceptance:** `_region_crop_origin_check` and `_still_frame_origin_check` ship with hostile tests for same-dimension wrong-region crop and wrong-timestamp still substitution; existing freeze/clean-edges/background checks remain green.

## 7. Release stop (non-negotiable)

This manifest records open loops and the order to close them. It does **not** authorize:

- any version bump, git tag, release branch, or CHANGELOG release entry;
- any package upload, registry submission, or directory submission (including Smithery, Glama, or any new directory);
- any deployment, release creation, or announcement;
- any merge of the Wave 3 draft PR until §1 is closed and a fresh independent review is recorded;
- any kernel-wave implementation until the human kernel-gate is reconciled;
- any bypass of the public-surface count tests in `tests/test_public_surface.py`.

After the open items close, the controller must publish a final coverage matrix, test + leak-audit receipts on the exact tip, known limitations, optional/deferred capability state, and a human-review checklist, then wait for explicit release authority.

## 8. Audit unblock checklist (controller)

- [ ] Wave 3 follow-up branch off `c0032d8` closes §1.1, §1.2, §1.3 in TDD order.
- [ ] `docs/status/2026-07-12-wishlist-draft-pr-status.md` and `docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md` updated with the new tip, exact test counts, and the fresh independent review verdict.
- [ ] Public-surface counts in `tests/test_public_surface.py` revisited only when a new Wave lands new commands/tools (none authorized by this manifest).
- [ ] `docs/superpowers/plans/2026-07-11-kinocut-ai-video-plan-index.md` checkbox progress updated for each closed/open transition.
- [ ] Sound program has a fresh Epoch estimate per leaf before each foundation/voice/post/assembly/ambience/QA/orchestration/scalability/adapter/benchmark story starts, and an actual-duration receipt after each closes.
- [ ] Final program verification gate (Plan 05 / `G015`) rerun on the exact tip before any release ask.
