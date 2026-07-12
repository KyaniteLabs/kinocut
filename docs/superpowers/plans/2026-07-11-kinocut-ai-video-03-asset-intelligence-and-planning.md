# Plan 03 — Wave 6 (Asset Intelligence) + Wave 7 (Editorial Planning & Continuity)

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change. No release actions (index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §5.3, §6 Wave 6–7, §7; coverage #19–20, #36–46.

> **For implementers:** Work task-by-task in bounded branches with independent review.

**Goal:** Make approved assets, beds, and prompts durably reusable and searchable, and add declarative editorial planning (beats, coverage, continuity) with honest, cost-aware regeneration advice — all as governed projections over the shipped dependency-free semantic index and the Plan 00 record model.

**Architecture:** Persist registries over Plan 00 contracts, not a new engine. The semantic index is already dependency-free and local — `kinocut/semantic/index.py` (`build_semantic_index`:128, `query_semantic_index`:181, `query_local_index`:221; models `SemanticIndex`:38, `SemanticQueryHit`:86, `SemanticQueryResponse`:97; hashing via `SemanticIndex.index_sha256`), surfaced today by `video_semantic_query` (`kinocut/server_tools_postrescue.py:30` → `semantic_query` `kinocut/postrescue.py:94` → `query_local_index`). Registries index approved `ClipVerdict`/`AssetRecord` projections and filter by verdict + rights. Prompt outcome memory links private prompt references/hashes to verdicts/defects/variants/final-uses. Editorial planning adds `BeatRequirement`, `ContinuityPlan`, and deterministic coverage/continuity projections; regeneration advice (#44) stays advisory and unavailable until cost/outcome data exists. Variant integration carries shared beats/protected-elements/approvals/lineage through the shipped `kinocut/workflow/variants.py` (`variant_ids`:38, `apply_variant_overrides`:47) without replacing variants.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, the pure-Python semantic index (no network/model), optional embedding/perceptual providers (fail-soft), pytest 8+, Ruff. No new FFmpeg surface except perceptual-fingerprint sampling in the optional provider.

## Global Constraints (subset — see index §3)

- Registries, coverage, continuity, and learning outputs are DERIVED projections over canonical records; they are rebuildable and never independent sources of truth (design §3.1).
- Approved clip reuse searches only verdict-compatible, rights-compatible records and returns why each result matched (design §5.3).
- Regeneration recommendations remain advisory and display evidence, estimated cost range, missing data, and alternatives; #44 is unavailable until enough cost/outcome data exists (design §5.3, §6 Wave 7).
- Exact duplicate detection is core; near-duplicate/perceptual is an optional fail-soft capability (design §5.3, coverage #39).
- Cross-project library reuse is explicit + human-authorized; stale/missing origins are reported (design §3.2).
- Variant integration retains current compatibility; no variant is replaced (coverage #46).
- MCP/Python/CLI parity; optional-capability fail-soft; no release actions (index §3, §3.6).

## File Structure

### Wave 6 — new production files

- `kinocut/aivideo/registry/clips.py` — persistent `ClipRecord` (over asset/verdict/defect/usage contracts) + usage-history events + exact-duplicate detection by `asset_id`.
- `kinocut/aivideo/registry/beds.py` — reusable bed subtype registry (rights, mood, tempo, audition + approval history).
- `kinocut/aivideo/registry/search.py` — approved-clip semantic search over `query_local_index`, filtered by verdict + rights, returning match rationale; optional embeddings/perceptual near-duplicate provider.
- `kinocut/aivideo/registry/prompt_memory.py` — private prompt references/hashes linked to verdicts, defects, variants, and final-use events (append-only).
- `kinocut/aivideo/registry/library.py` — explicit cross-project library publication (human-authorized snapshot of approved records; origin IDs/hashes retained; stale-origin reporting).
- Surfaces: `video_clip_registry`, `video_clip_search`, `video_bed_registry`, `video_prompt_memory`, `video_library_publish`.

### Wave 7 — new production files

- `kinocut/aivideo/planning/beats.py` — `BeatRequirement` + clip-to-beat satisfaction bindings (semantic beat map).
- `kinocut/aivideo/planning/coverage.py` — deterministic coverage report projection over acceptance spec + beat map + verdicts + index (read-only; no new storage).
- `kinocut/aivideo/planning/continuity_plan.py` — `ContinuityPlan` bound to beat/shot IDs (declared inter-shot expectations).
- `kinocut/aivideo/planning/continuity_evidence.py` — deterministic adjacent-clip metrics + optional identity/VLM evidence + cost-aware repair/regenerate comparison (#44 gated on data).
- `kinocut/aivideo/planning/variant_integration.py` — carry beats/protected-elements/approvals/lineage through workflow variants.
- Surfaces: `video_beat_map`, `video_coverage_report`, `video_continuity_plan`, `video_continuity_evidence`, `video_regen_advice`.

### New tests

- Wave 6: `tests/test_registry_clips.py`, `tests/test_registry_beds.py`, `tests/test_registry_search.py`, `tests/test_prompt_memory.py`, `tests/test_registry_library.py`, `tests/test_wave6_surfaces.py`.
- Wave 7: `tests/test_planning_beats.py`, `tests/test_planning_coverage.py`, `tests/test_continuity_plan.py`, `tests/test_continuity_evidence.py`, `tests/test_variant_integration.py`, `tests/test_wave7_surfaces.py`.

### Documentation

- `docs/AI_VIDEO_ASSETS.md`, `docs/AI_VIDEO_PLANNING.md`; additive CLI/TOOLS/PYTHON refs. No release entries.

---

## PR 6.1 — Approved clip and bed registries (#20, #36, #38, #41)

### Task 1: Persistent clip registry + usage history + exact duplicates

**Files:** Create `kinocut/aivideo/registry/clips.py`; Test `tests/test_registry_clips.py`.

**Interfaces:** Consumes Plan 00 `AssetRecord`/`ClipVerdict`/`GenerationLineage`/`UsageEvent`, project store.

- [ ] **Step 1: Failing tests** — a `ClipRecord` persists over asset/verdict/defect/usage contracts; usage-history events append; two identical-byte assets are detected as exact duplicates by `asset_id` and not double-registered; only approved verdicts are surfaced as reusable.
- [ ] **Step 2: RED** → **Step 3: Implement** the registry as a projection with append-only usage events.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_registry_clips.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(registry): persistent approved-clip registry with usage history"`.

### Task 2: Reusable bed registry

**Files:** Create `kinocut/aivideo/registry/beds.py`; Test `tests/test_registry_beds.py`.

- [ ] **Step 1: Failing tests** — bed subtype records carry rights, mood, tempo, audition + approval history; approval history is append-only and never auto-updated by audition.
- [ ] **Step 2: RED** → **Step 3: Implement** the bed registry over Plan 02's bed artifacts.
- [ ] **Step 4: Green + commit** — `python3 -m pytest -q tests/test_registry_beds.py && git commit -m "feat(registry): reusable bed registry"`.

---

## PR 6.2 — Semantic and near-duplicate retrieval (#37, #39)

### Task 3: Approved-clip search + optional near-duplicate

**Files:** Create `kinocut/aivideo/registry/search.py`; Test `tests/test_registry_search.py`.

**Interfaces:** Consumes `query_local_index` (semantic/index.py:221), `SemanticQueryResponse` (:97); optional embeddings/perceptual fingerprint provider.

- [ ] **Step 1: Failing tests** — search returns only verdict-compatible + rights-compatible records with a per-result match rationale; exact duplicates always detected; near-duplicate perceptual matching is available only when the optional provider is present, else a typed `capability_unavailable` finding with deterministic exact-match results intact.
- [ ] **Step 2: RED** → **Step 3: Implement** the filtered search over the dependency-free index; optional embedding/perceptual layer is additive and fail-soft.
- [ ] **Step 4: Green (fixtures)** — identical + perceptually similar clips, conflicting rights/verdicts.
- [ ] **Step 5: Commit** — `git commit -m "feat(registry): approved-clip search with optional near-duplicate"`.

### Task 4: Cross-project library publication

**Files:** Create `kinocut/aivideo/registry/library.py`; Test `tests/test_registry_library.py`.

- [ ] **Step 1: Failing tests** — publishing an approved record to the configured library is human-authorized; library entries retain origin record IDs + hashes; a stale/missing origin is reported, never silently treated as current approval; Kinocut never scans unrelated directories.
- [ ] **Step 2: RED** → **Step 3: Implement** explicit snapshot publication + stale-origin reporting.
- [ ] **Step 4: Green + commit** — `python3 -m pytest -q tests/test_registry_library.py && git commit -m "feat(registry): explicit cross-project library publication"`.

> **Parallel note:** PR 6.2 and PR 6.3 may run concurrently after PR 6.1 (design §7).

---

## PR 6.3 — Prompt outcome memory (#40)

### Task 5: Private prompt-outcome records

**Files:** Create `kinocut/aivideo/registry/prompt_memory.py`; Test `tests/test_prompt_memory.py`.

**Interfaces:** Consumes Plan 00 `PromptOutcome`, asset lineage, verdicts.

- [ ] **Step 1: Failing tests** — prompt references are stored as private hashes (never public prompt text) linked to verdicts, defects, variants, and final-use events; records are append-only; public export exposes only opt-in summaries/hashes.
- [ ] **Step 2: RED** → **Step 3: Implement** the append-only outcome records built from lineage + verdict.
- [ ] **Step 4: Green (privacy)** — `python3 -m pytest -q tests/test_prompt_memory.py tests/test_receipt_privacy.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(registry): private prompt outcome memory"`.

### Task 6: Wave 6 surfaces + gate

**Files:** MCP/CLI/Python for the five Wave 6 surfaces; Test `tests/test_wave6_surfaces.py`.

- [ ] Steps: failing parity tests → RED → implement (`@mcp.tool()`/`@_safe_tool`/`_result`, `CommandRunner.register`) → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo/registry` → leak audit → `git commit -m "feat(registry): wave 6 asset-intelligence surfaces"`.

---

## PR 7.1 — Beat map, coverage, and continuity plan (#42–43, #45)

### Task 7: Beat requirements + deterministic coverage + continuity plan

**Files:** Create `kinocut/aivideo/planning/{beats,coverage,continuity_plan}.py`; Test `tests/test_planning_beats.py`, `tests/test_planning_coverage.py`, `tests/test_continuity_plan.py`.

**Interfaces:** Consumes Plan 00 acceptance spec + verdict/asset records, the semantic index.

- [ ] **Step 1: Failing tests** — `BeatRequirement`s bind planned beats to clip satisfaction; the coverage report is a deterministic read-only projection over acceptance spec + beat map + verdicts + index (no new storage); `ContinuityPlan` binds declared inter-shot expectations to beat/shot IDs.
- [ ] **Step 2: RED** → **Step 3: Implement** the three planning primitives as projections.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_planning_beats.py tests/test_planning_coverage.py tests/test_continuity_plan.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(planning): beat map, coverage report, continuity plan"`.

---

## PR 7.2 — Continuity evidence and regeneration advice (#19, #44 gated)

### Task 8: Adjacent-clip metrics + gated regen advice

**Files:** Create `kinocut/aivideo/planning/continuity_evidence.py`; Test `tests/test_continuity_evidence.py`.

**Interfaces:** Consumes continuity plan, optional identity/VLM providers, Plan 03 cost/outcome data (via prompt memory + Plan 04 cost ledger), `kinocut/visual_intelligence/` if present.

- [ ] **Step 1: Failing tests** — deterministic adjacent-clip metrics compute without ML; optional identity/VLM evidence is fail-soft; regeneration advice (#44) is `capability_unavailable` until enough cost/outcome data exists, and when available it displays evidence, estimated cost range, missing data, and alternatives — never a bare verdict.
- [ ] **Step 2: RED** → **Step 3: Implement** the metrics + the gated advisor; honesty about missing data is mandatory.
- [ ] **Step 4: Green (fixtures)** — adjacent-clip continuity pass/fail, insufficient-data gating.
- [ ] **Step 5: Commit** — `git commit -m "feat(planning): continuity evidence and gated regeneration advice"`.

---

## PR 7.3 — Variant contract integration (#46)

### Task 9: Carry beats/approvals/lineage through variants

**Files:** Create `kinocut/aivideo/planning/variant_integration.py`; Test `tests/test_variant_integration.py`.

**Interfaces:** Consumes `kinocut/workflow/variants.py` (`variant_ids`:38, `apply_variant_overrides`:47), Plan 00 approvals/lineage.

- [ ] **Step 1: Failing tests** — shared beats, protected elements, approvals, and lineage propagate through shipped workflow variants; existing variant behavior and separate receipts are unchanged (variant isolation preserved); sources are never override targets.
- [ ] **Step 2: RED** → **Step 3: Implement** the integration layer over existing variants; no variant replaced.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_variant_integration.py tests/test_workflow_variants.py` (existing variant tests still pass).
- [ ] **Step 5: Commit** — `git commit -m "feat(planning): variant contract integration without replacing variants"`.

### Task 10: Wave 7 surfaces + full-suite gate

**Files:** MCP/CLI/Python for the Wave 7 surfaces; Test `tests/test_wave7_surfaces.py`.

- [ ] Steps: failing parity tests → RED → implement surfaces → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo/planning` → leak audit → `git commit -m "feat(planning): wave 7 editorial-planning surfaces"`.

---

## Wave 6–7 completion criteria

- Registries persist approved clips/beds as projections with append-only usage/approval history; exact duplicates detected; near-duplicate fail-soft; library publication explicit + human-authorized with stale-origin reporting.
- Prompt memory is private (hashes only) and append-only.
- Beat map/coverage/continuity plan are deterministic projections; regeneration advice (#44) is honestly gated and evidence-backed.
- Variant integration preserves all existing variant behavior and isolation.
- Design §8 fixture families for duplicate/similar clips, conflicting rights/verdicts, prompt variants, usage history, and variant isolation are exercised; MCP/Python/CLI parity + backward fixtures green; full suite green; canonical import passes; Ruff clean; modules ≤ 800 LOC.
- Independent review approved; no self-approval; no release actions (index §3.6).
- Downstream: Plan 04 (review/CLI/learning) consumes these registries, coverage, and cost inputs.
