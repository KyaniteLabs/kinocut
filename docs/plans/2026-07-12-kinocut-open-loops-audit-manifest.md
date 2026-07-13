# Kinocut all-open-loops controller audit and execution manifest

> **Implementation amendment:** The inventory below is the pre-ready-units audit snapshot.
> Governed audio-bed composition, voice seam checks, approved-asset registry queries, subtitle QA,
> deterministic graphics, and the `kinocut_sound` foundation have since landed in the reviewed
> integration checkpoint at `090424c`. See
> [`../status/2026-07-12-ready-units-integration-checkpoint.md`](../status/2026-07-12-ready-units-integration-checkpoint.md)
> for exact evidence. Unamended open/closed counts below are historical and must not be used as the
> current completion claim.
>
> **Sound amendment:** S1-S4 are complete on reviewed 2026-07-13 checkpoints. See
> [`../status/2026-07-13-sound-s2-s4-integration-checkpoint.md`](../status/2026-07-13-sound-s2-s4-integration-checkpoint.md).
> and [`../status/2026-07-13-sound-s3-integration-checkpoint.md`](../status/2026-07-13-sound-s3-integration-checkpoint.md).
> S5, S7, and S8 are next; the historical sound inventory below is superseded.

**Status:** decision-complete repo-native manifest; audit only — no implementation, push, merge, tag, publish, deploy, or release authorized by this document.

**Audit base:** `c0032d8` on `codex/niko-plan-audit`.

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

**Audit method:** every claimed capability was checked against the source/test tree at `c0032d8` before being marked closed. Items marked open cite the exact file/function gap. The three G006 blockers were verified by reading `kinocut/aivideo/salvage.py`, `kinocut/aivideo/protection.py`, `kinocut/engine_body_swap.py`, and the focused tests. They are now closed on `codex/niko-close-open-loops` at reviewed implementation tip `7d16d525121f5bf8e9e427798304e89057844051` (hygiene tip `47731e9`).

**Release stop:** non-negotiable. This manifest authorizes no version bump, tag, package upload, registry submission, deployment, release creation, or announcement. It records the open-loop inventory and the order in which the controller should close it.

## 1. The three current PR blockers (G006)

The draft PR status (`docs/status/2026-07-12-wishlist-draft-pr-status.md`) and the verification receipt (`docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md`) record the G006 closeout on the Wave 3 tip. The architecture review is APPROVE (279 focused pass); the security review is CLEAR (102 + 57 focused pass). The whole repository suite passed on the reviewed implementation tip: 3088 passed, 18 skipped, 8 warnings, 552.04s. This is a merge-ready bounded checkpoint; no release, tag, package, deploy, or announcement is authorized.

Forgejo run 142 subsequently exposed Debian/root/FFmpeg 5 compatibility defects on publication tip `411bc529`: six failures caused by root-writable verified snapshots and FFmpeg 5 `showinfo` records without `duration_time`. The reviewed successor `46e5e0d` seals snapshots with immutable Linux memfd seals, fails closed when seals are unavailable, and makes temporal diagnostics FFmpeg 5 compatible without accepting path/banner/component false positives. Its exact root-container replay passed 22 tests; independent review is APPROVE/CLEAR with 49 focused pass; the Niko whole suite passed 3104 tests with 18 skipped and 8 warnings in 536.51s. Exact-tip Forgejo CI remains required before merge. This successor does not change the standing release stop.

### 1.1 Persisted mutation fingerprint and authorization references are absent from salvage lineage

- **Status at audit base (`c0032d8`):** open.
- **Status at this manifest update:** closed by `345c2dc fix(aivideo): persist salvage mutation_fingerprint and authorization refs` on `codex/niko-close-open-loops`. The manifest schema is bumped to v2; `mutation_fingerprint(intent)` and `authorization_decision_ids` are persisted in `kinocut/aivideo/salvage_lineage.py::manifest_payload`. `_read_prior_derivative` recomputes the same descriptor/audio-bound intent via `_mutation_intent` + `_salvage_audio_fingerprint` and rejects any persisted manifest whose recomputed fingerprint differs from the stored value, whose authorization refs are missing/stale/superseded/not human-bound to that fingerprint, or where a protected lock now requires fresh approval (`assert_no_protected_collision` is re-run on replay). Schema-v1 backward behavior is explicit: v1 manifests are accepted on read but treated as unauthenticated, so they cannot bypass current authorization. Hostile tests cover fingerprint tamper, authorization-ref tamper, stale/superseded auth replay, protected-state changes after render, v1 idempotent replay, v1 plus new lock, and successful idempotent v2 replay through a protected lock. Privacy: authorization IDs are record IDs (already `sha256:` digests); no host paths, prose, or credentials enter the manifest. The `target_ref` binding gap in the replay resolver was subsequently closed by `7d16d52 fix(aivideo): unify salvage authorization resolver with protection gate`, which exposes a single `protection.active_human_approval_bound_to` consumed by both `_authorized` and salvage-lineage replay verification.
- **Original gap (for reference).** `kinocut/aivideo/salvage.py::create_salvage_derivative` built a `MutationIntent` via `_mutation_intent(...)` and passed it to `assert_no_protected_collision`, but the exact `mutation_fingerprint(intent)` and the claimed `authorization_decision_ids` were not written into the persisted salvage-lineage manifest, and `_read_prior_derivative` re-derived intent from `policy_hash` only.
- **Owner.** Wave 3 salvage owner (`kinocut/aivideo/salvage.py`, `kinocut/aivideo/salvage_lineage.py`).

### 1.2 `trim_audio` body-swap proof does not bind to the declared trim of the approved source

- **Status at audit base (`c0032d8`):** open.
- **Status at this manifest update:** closed by `c80c579 fix(aivideo): prove approved-source trim_audio prefix` on `codex/niko-close-open-loops`. `_declared_trim_proof` verifies the output audio packet sequence is a bounded prefix of the approved source within tolerance; the `trim_audio` verdict is `approved_audio_trimmed`; hostile tests cover equal-length substitution, volume-scaled re-encode, descriptor-backed hostile render, and faithful `-c:a copy -t cut`.
- **Original gap (for reference).** `_proof` compared source and output `_audio_fingerprint` values and accepted any "changed" verdict, so unrelated audio of the correct length could pass the `trim_audio` path.
- **Owner.** Wave 3 body-swap owner (`kinocut/engine_body_swap.py`).

### 1.3 Independent origin proofs for region-crop and still-frame salvage are missing (freeze prefix, freeze tail, clean-edges, and background are closed)

- **Status at audit base (`c0032d8`):** open (region-crop origin and still-frame origin); the freeze prefix check was also missing (only the tail and extension were bound).
- **Status at this manifest update:** closed by `a3b51fc fix(aivideo): bind entire salvage frame range to descriptor` on `codex/niko-close-open-loops`. `_region_crop_origin_check` independently re-renders the declared crop and compares every frame hash; `_still_frame_origin_check` re-extracts the declared timestamp in a common rgb24 space and compares pixels; `_freeze_checks` now compares every pre-transition, transition, and extension frame against the source hash stream (the prefix loop was the missing piece at audit base). `BACKGROUND_ONLY` uses the existing 3-frame `_crop_origin_check` (start/mid/end timestamps), not a separate FFV1-backed comparison. This is noted as a defense-in-depth limitation — only three representative frames are verified, not every frame — without reopening the scoped G006 blocker. Hostile tests cover wrong-offset region crop, synthetic still, and prefix-frame forgery.
- **Already closed before this wave (do not redo):**
  - **clean_edges** — `_clean_edges_origin_check` independently re-selects the source interval and compares frame hashes; `32acd80 fix(aivideo): verify clean-edge origin independently` plus `test_clean_edges_rejects_same_duration_from_wrong_source_interval` and `test_clean_edges_rejects_systematic_trim_interval_defect` cover it. `dbb87e4 fix(aivideo): keep salvage sources descriptor-bound` and `41bc543 fix(aivideo): bind body-swap authorization policy` plus `6fe7995 test(aivideo): exercise descriptor-bound hostile renders` close the descriptor-bound hostile-render loop.
- **Owner.** Wave 3 salvage owner (`kinocut/aivideo/salvage.py`, `kinocut/aivideo/salvage_checks.py`).

### 1.4 Wave 3 PR unblock sequence

G006 sections 1.1, 1.2, and 1.3 are closed on `codex/niko-close-open-loops`. The integration order was 1.2 (`c80c579`) → 1.3 (`a3b51fc`) → 1.1 (`345c2dc`) → resolver (`7d16d52`). The audit snapshot was `c0032d8`; the remediation sequence was integrated onto canonical base `4b3a8af`, not branched from the audit snapshot. The whole gate ran on the reviewed implementation tip `7d16d525121f5bf8e9e427798304e89057844051` (hygiene tip `47731e9`): architecture APPROVE (279 focused pass), security CLEAR (102 + 57 focused pass), whole suite 3088 passed, 18 skipped, 8 warnings, 552.04s. The import/diff/forbidden/readiness/leak gates are recorded as pass. This is a merge-ready bounded checkpoint; it is not release-ready, publish-ready, or deploy-ready.

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
| 8 | Receipt-Backed Editing | closed | `AiVideoReceiptSection` + `PreservationProof` exist (`kinocut/contracts/receipt_ai_video.py`, `tests/test_receipt_ai_video.py`); body-swap and salvage receipts now carry the strengthened evidence landed in §1.1/§1.2/§1.3 | 00 / PRs 1.1, 3.2, 3.3 |
| 9 | Motion Strip | closed | `kinocut/aivideo/inspection/motion_strip.py::build_motion_strip`, `tests/test_inspection_motion_strip.py` | 01 / PR 2.2 |
| 10 | Late-Frame QA | closed | `kinocut/aivideo/inspection/samplers.py::sample_decoded_timestamps` (0/25/50/75/95/last policy), `tests/test_inspection_samplers.py` | 01 / PR 2.2 |
| 11 | Text-Drift Check | closed | `extract_region_crops`, declared-region sampler, `tests/test_inspection_samplers.py` | 01 / PR 2.2 |
| 12 | Temporal Inspect | closed | `kinocut/aivideo/surfaces.py::run_inspection_operation`, `tests/test_inspection_surfaces.py` | 01 / PR 2.2 |
| 13 | Loop Integrity Check | closed | `_text_drift_findings`/opening-closing difference in `kinocut/aivideo/inspection/temporal_checks.py`, `tests/test_inspection_temporal_checks.py` | 01 / PR 2.3 |
| 14 | Frozen/Black/Corrupt Detection | closed | `_black_findings`/`_frozen_findings`/`_corrupt_findings`, `tests/test_inspection_temporal_checks.py` | 01 / PR 2.3 |
| 15 | Motion Intent Check | closed (optional) | `analyze_optional_visual_findings` returns `provider_not_configured` deterministically; `tests/test_inspection_providers.py` | 01 / PR 2.4 |
| 16 | Generative Defect Report | closed (optional) | optional visual provider hook + deterministic findings aggregation | 01 / PRs 2.3–2.4 |
| 17 | Body Swap | closed | `kinocut/engine_body_swap.py::body_swap` ships pad/trim/reject with descriptor-bound `_declared_trim_proof` (`c80c579`); §1.2 trim proof closed | 02 / PR 3.2 |
| 18 | Salvage Clip | closed | `kinocut/aivideo/salvage.py::create_salvage_derivative` ships 5 recipes with descriptor-bound origin checks (`a3b51fc`) and v2 salvage-lineage schema persisting `mutation_fingerprint` + `authorization_decision_ids` (`345c2dc`); §1.1 and §1.3 closed | 02 / PR 3.3 |
| 19 | Continuity Assistant | open | no adjacent-clip rubric; optional VLM/embedding findings not wired | 03 / PR 7.2 |
| 20 | Approved Clip Reuse | open | semantic index exists (`kinocut/semantic/index.py`); no verdict/rights-filtered approved-clip registry query | 03 / PR 6.1 |
| 21 | Protected Timeline Regions | deferred | blocked behind kernel wave (Plan 05 / PR K.1) — contract not implemented | 05 |
| 22 | Resume-Aware Rendering | partial | workflow resume exists (`kinocut/workflow/executor.py`); revision/DAG changed-stage reuse not lifted into the kernel | 05 / PR K.1 |
| 23 | Audio Bed | open | `audio_compose`/`video_duck_audio` exist (`kinocut/server_tools_audio.py`); no governed one-shot bed facade with crossfade, fades, normalization, and exact duration policy | 02 / PR 4.1 |
| 24 | Bed Audition | open | no labeled multi-bed audition recipe | 02 / PR 4.1 |
| 25 | Voice Style Check | open | no pace/pitch/cadence/silence seam metric | 02 / PR 4.2 |
| 26 | Voice Identity Check | open | no speaker-embedding provider | 02 / PR 4.2 |
| 27 | ASR Timestamp Clamp | open | transcription parses segments (`kinocut/ai_engine/transcribe.py`) but no canonical EOF clamp before derived metrics | 01/02 / PRs 1.2, 4.2 |
| 28 | Audio Preservation Verification | closed | `_audio_evidence`/`_audio_fingerprint` exist (`kinocut/engine_body_swap.py`); `_declared_trim_proof` strengthens the `trim_audio` case (`c80c579`) | 02 / PR 3.2 |
| 29 | Audio Duration Safety | closed | `add_audio(..., duration_policy=...)` (`kinocut/engine_audio_ops.py`, `tests/test_add_audio_duration_policy.py`) | 01 / PR 1.1 |
| 30 | Audio Seam Report | open | composition over #25–29; no seam report | 02 / PR 4.2 |
| 31 | ASS Subtitle Support | closed | `kinocut/engine_subtitles.py`, `kinocut/subtitles_common.py`, `tests/test_subtitles_ass_and_dimension.py` | 01 / PR 1.2 |
| 32 | Dimension-Aware SRT/VTT Rendering | closed | same; `tests/test_subtitles_ass_and_dimension.py` | 01 / PR 1.2 |
| 33 | Subtitle Safe-Area Check | open | no subtitle cue/platform-overlay analyzer | 02 / PR 5.1 |
| 34 | Subtitle Temporal QA | partial | rescue verifier covers EOF (`tests/test_subtitles_eof.py`); overlap/gap/reading-speed/missing-line findings absent | 02 / PR 5.1 |
| 35 | Deterministic Graphics Layer | open | text/overlay/compositor primitives exist; no governed recipe bound to source assets/fonts and receipt hashes | 02 / PR 5.2 |
| 36 | Clip Index | open | semantic index has stable IDs; no persistent approved-asset `ClipRecord` registry | 03 / PR 6.1 |
| 37 | Semantic Clip Search | closed | `video_semantic_query`/`kinocut/semantic/index.py` | 03 / PR 6.2 (extend for clips) |
| 38 | Generation Lineage | partial | `GenerationLineage` contract + salvage lineage (`dbb87e4`); cross-reference family graph not built | 03 / PR 6.1 |
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

**Closed:** 24 of 61 (including 2 closed-optional: #15, #16). **Partial:** 11. **Open:** 23. **Deferred (kernel/data):** 3 (#21, #44, #58). Wave 3 trio §1.1/§1.2/§1.3 is closed on `codex/niko-close-open-loops`; items #17 and #18 move from partial to closed. The G006 review is complete: architecture APPROVE (279 focused pass), security CLEAR (102 + 57 focused pass), whole suite 3088 passed, 18 skipped, 8 warnings, 552.04s on reviewed tip `7d16d525121f5bf8e9e427798304e89057844051`. This is a merge-ready bounded checkpoint; it is not release-ready, publish-ready, or deploy-ready.

### 2.2 Sound (`kinocut_sound`) program

The historical statement that this program is entirely open is superseded. Current reviewed state:

- **S1 complete:** standalone plans, timeline, routing, delivery, consent, receipt, capability,
  format, line, and render-fingerprint contracts.
- **S2 complete:** authorization ledger, leases, revocation race handling, transitive lineage,
  privacy-safe audit context, per-source blend/cloud egress, and quarantine/deletion outcomes.
- **S3 complete:** sealed adapter registry, versioned presets/config, exact local/cloud provider
  policy, complete render fingerprint, and authorization-aware cache with real S2 lineage.
- **S4 complete:** strict generic/WF parsing and deterministic pure episode planning for dialogue,
  narration, action, voiceover, chapter cards, beats, pacing, silence, routing, and Foley contracts.
- **S5-S15 open:** S5 voice, S7 post/spatial, and S8 ambience are parallel-ready. S6/S10 depend on
  S5; S9 depends on S5+S7+S8; S11 depends on S4+S7+S9.

No sound-specific public CLI command or MCP tool is registered. Public parity and concrete host
binding remain the serialized S12/S13 joins. Existing Kinocut audio bridges remain downstream
composition targets, not proof that those joins are complete.

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
Wave 3  ✓ verdict + protection + body swap + salvage  (PRs 3.1 ✓, 3.2 ✓, 3.3 ✓) — G006 closed, merge-ready checkpoint
            └─ §1 blockers (mutation/auth persistence, trim proof, region/still origin) — closed
Wave 4  ◻ audio continuity (audio-bed, audition, voice style/identity, ASR clamp, seam report)
Wave 5  ◻ subtitle/graphics QA (safe-area, temporal QA, deterministic graphics)
Wave 6  ◻ asset intelligence (clip index, semantic/near-duplicate retrieval, prompt outcome, bed registry)
Wave 7  ◻ editorial planning (beat map, coverage, continuity plan/evidence, regen advice, variant integration)
Wave 8  ◻ review and approval (review package, timestamped decisions, human gate, limitation ledger, invalidation)
Wave 9  ◻ CLI/agent ergonomics (namespaced CLI, agent-mode output, capability discovery, next action, doctor migrations)
Wave 10 ◻ learning and benchmark (recipe capture, cost ledger, learning report, defect-to-prompt, acceptance benchmark)
Wave K  ◻ protected-timeline kernel — GATED behind human kernel-gate reconciliation
Sound   ◻ 15-leaf `kinocut_sound` program — S1-S4 ✓; S5/S7/S8 next → S6/S9/S10 → S11 QA/metadata →
            S12 public parity → S13 host joins → S14 benchmark → S15 acceptance
            (S9 waits for S5+S7+S8; S11 waits for S4+S7+S9)
```

**Hard parallelism rule** (from `docs/plans/2026-07-12-wishlist-parallel-execution.md`): at most four disjoint feature authors plus one controller/reviewer. Public-surface joins (MCP registry, CLI parser/dispatch, Python client aggregate surfaces, shared defaults/validation/limits, package exports, public-surface count tests, program ledger) are controller-serialized; one integration at a time.

**Sound program serialization:** the authoritative program has 15 bounded leaves. S12 serializes
public parity after implemented use cases freeze; S13 then binds Kinocut/WF/legacy hosts before the
S14 benchmark and S15 final acceptance. The adapter cannot be deferred until after benchmarking.

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

1. **Wave 3 follow-ups** — §1.1, §1.2, §1.3 are closed on `codex/niko-close-open-loops` (commits `c80c579`, `a3b51fc`, `345c2dc`, `7d16d52`). The full gate ran on the reviewed implementation tip `7d16d525121f5bf8e9e427798304e89057844051` (hygiene tip `47731e9`): architecture APPROVE (279 focused pass), security CLEAR (102 + 57 focused pass), whole suite 3088 passed, 18 skipped, 8 warnings, 552.04s. The draft PR status and verification receipt are updated with the closeout evidence. This is a merge-ready bounded checkpoint; it is not release-ready, publish-ready, or deploy-ready.
2. **Wave 4 audio continuity** — after Wave 3 closes; PRs 4.1 (bed + audition) and 4.2 (voice style/identity + seam report + ASR clamp) can start in parallel once their contracts stabilize.
3. **Wave 5 subtitle/graphics QA** — PRs 5.1 (safe-area + temporal QA) parallel to 4.1; 5.2 (deterministic graphics) after Wave 0.
4. **Wave 6 asset intelligence** — PRs 6.1 (registries), 6.2 (semantic + near-duplicate retrieval), 6.3 (prompt outcome memory). 6.2/6.3 parallel after 6.1.
5. **Wave 7 editorial planning** — PRs 7.1 (beat map + coverage + continuity plan), 7.2 (continuity evidence + regen advice; #44 deferred on data), 7.3 (variant contract integration).
6. **Wave 8 review/approval** — PRs 8.1 (review package + timestamped decisions + limitation ledger), 8.2 (human gate + generalized approval invalidation).
7. **Wave 9 CLI/agent ergonomics** — PRs 9.1 (namespaced CLI + agent-mode output) and 9.2 (capability discovery + next action + doctor migrations) parallel after their contracts.
8. **Wave 10 learning/benchmark** — PR 10.1 (recipe + cost + learning reports) after 6.x and 8.x; PR 10.2 (acceptance benchmark) after all feature waves.
9. **Sound program** — authoritative 15-leaf graph; S5/S7/S8 next, then dependent S6/S9/S10/S11,
   followed by S12 public parity and S13 host joins before the S14 benchmark and S15 acceptance.
10. **Kernel wave (gated)** — PR K.1 (protected timeline regions + stage reuse) only after explicit human kernel-gate reconciliation; the durable kernel contract named in `docs/plans/2026-07-09-kinocut-trusted-execution-layer.md` must exist first.

## 6. Per-item acceptance gates

Every closed and every open item carries the same gate shape:

1. **Contract** — strict Pydantic model under `kinocut/contracts/`; canonical `record_id` (sha256 over sorted-key compact JSON); privacy closed-bounded codes; explicit `record_kind`.
2. **Engine** — focused module under `kinocut/aivideo/`, `kinocut/engine_*.py`, or `kinocut_sound/`; uses `_escape_ffmpeg_filter_value` for every user-controlled filter value; uses custom error types from `kinocut/errors.py`; bounded subprocess timeouts via `DEFAULT_FFMPEG_TIMEOUT`; no module > 800 LOC or function > 80 lines; no dead code.
3. **Privacy** — receipts/manifests carry project-relative paths and hashes only; raw prompts, host paths, and credentials are structurally unrepresentable; the public leak audit (`scripts/git-professional-audit.sh`, `scripts/repo-readiness-audit.py`, `.github/scripts/check-forbidden-artifacts.py`) is clean.
4. **Surface parity** — MCP tool, Python client method, and flat CLI command call the same adapter; `tests/test_public_surface.py` pins the expected counts and identities.
5. **Tests** — focused unit + real-FFmpeg integration; privacy/integrity/hostility cases; idempotency and tamper-fail-closed cases; backward readers for prior receipt/record versions.
6. **Review** — independent author/reviewer roles; the author does not self-approve; final architecture + security review recorded as APPROVE/CLEAR with exact tip SHA `7d16d525121f5bf8e9e427798304e89057844051`.
7. **Receipts** — issue/PR receipts cite exact commit, focused/full test counts, skips/warnings, elapsed time, CI status, compatibility risks, and remaining external gates. The controller replaces task-local receipts with exact-tip receipts before describing a draft as merge-ready.

For the §1 blockers specifically:

- **§1.1 acceptance (closed by `345c2dc` on `codex/niko-close-open-loops`):** manifest schema bumped to v2; persisted `mutation_fingerprint` and `authorization_decision_ids`; `kinocut/aivideo/salvage_lineage.py::read_prior_derivative` rejects mismatched or stale-authorization manifests, re-runs `assert_no_protected_collision` on replay, and defines explicit safe v1 backward behavior; hostile tests cover fingerprint tamper, auth-ref tamper, stale/superseded auth replay, new protected lock after render, v1 idempotent replay, v1 + new lock, and successful idempotent v2 replay through a fresh protected lock. The replay resolver `target_ref` binding was subsequently unified with the protection gate by `7d16d52`.
- **§1.2 acceptance (closed by `c80c579`):** `_declared_trim_proof` verifies output audio is a bounded prefix of the approved source within tolerance; `expected="approved_audio_trimmed"`; hostile-prefix tests for equal-length substitution, volume-scaled re-encode, descriptor-backed hostile render, and faithful copy.
- **§1.3 acceptance (closed by `a3b51fc`):** `_region_crop_origin_check` and `_still_frame_origin_check` ship with hostile tests for same-dimension wrong-region crop and synthetic still substitution; `_freeze_checks` now binds the entire frame range (prefix + transition + extension); `BACKGROUND_ONLY` uses the existing 3-frame `_crop_origin_check` (start/mid/end), noted as a defense-in-depth limitation without reopening the scoped G006 blocker.

## 7. Release stop (non-negotiable)

This manifest records open loops and the order to close them. It does **not** authorize:

- any version bump, git tag, release branch, or CHANGELOG release entry;
- any package upload, registry submission, or directory submission (including Smithery, Glama, or any new directory);
- any deployment, release creation, or announcement;
- any merge of the Wave 3 draft PR until the controller confirms the G006 closeout and publishes the final receipt set;
- any kernel-wave implementation until the human kernel-gate is reconciled;
- any bypass of the public-surface count tests in `tests/test_public_surface.py`.

After the open items close, the controller must publish a final coverage matrix, test + leak-audit receipts on the exact tip, known limitations, optional/deferred capability state, and a human-review checklist, then wait for explicit release authority.

## 8. Audit unblock checklist (controller)

- [x] Wave 3 remediation closes G006 sections 1.1, 1.2, and 1.3 in TDD order (`c80c579`, `a3b51fc`, `345c2dc`, `7d16d52` on `codex/niko-close-open-loops`), using `c0032d8` as the audit snapshot and `4b3a8af` as the canonical integration base.
- [x] `docs/status/2026-07-12-wishlist-draft-pr-status.md` and `docs/proofs/wishlist-draft/VERIFICATION_RECEIPT.md` updated with the reviewed implementation tip `7d16d525121f5bf8e9e427798304e89057844051` (hygiene tip `47731e9`), exact test counts, and the review verdicts (architecture APPROVE, security CLEAR).
- [x] Whole-gate checklist complete on the reviewed implementation tip: 3088 passed, 18 skipped, 8 warnings, 552.04s; architecture 279 focused pass; security 102 + 57 focused pass; body-swap focused 22 (not 24); import/diff/forbidden/readiness/leak gates as recorded.
- [ ] Public-surface counts in `tests/test_public_surface.py` revisited only when a new Wave lands new commands/tools (none authorized by this manifest).
- [ ] `docs/superpowers/plans/2026-07-11-kinocut-ai-video-plan-index.md` checkbox progress updated for each closed/open transition.
- [ ] Sound program has a fresh Epoch estimate per leaf before each foundation/voice/post/assembly/ambience/QA/orchestration/scalability/adapter/benchmark story starts, and an actual-duration receipt after each closes.
- [ ] Final program verification gate (Plan 05 / `G015`) rerun on the exact tip before any release ask.
