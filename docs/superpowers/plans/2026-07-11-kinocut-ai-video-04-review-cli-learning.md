# Plan 04 — Wave 8 (Review & Approval) + Wave 9 (CLI & Agent Ergonomics) + Wave 10 (Learning & Regression)

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change. No release actions (index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §4.8–4.10, §6 Wave 8–10, §8; coverage #47–61.

> **For implementers:** Work task-by-task in bounded branches with independent review.

**Goal:** Assemble the standard human-review package and fail-closed publication gate, add namespaced/agent-friendly CLI and stable capability discovery, and close the loop with recipe/cost/learning reports plus the versioned 61-item acceptance benchmark.

**Architecture:** Compose over everything landed in Plans 00–03. The review package assembles inspection artifacts (Plan 01), seam/subtitle/preservation reports (Plan 02), receipt, known limitations, checklist, and approval state (Plan 00). Timestamped review decisions generalize the existing exact-hash approval mechanism — today `EditApproval` (`kinocut/semantic/edl.py:167`, `validate_approval_hash`:188) binds an approval to an exact EDL hash and `kinocut/workflow/executor.py` resume already fails on hash mismatch (`_step_reusable`:386, `_load_resume`:342) — into a general `ReviewDecision`/`ApprovalState` dependency fingerprint (Plan 00 §4.9). The human gate reuses the shipped `video_release_checkpoint` (`kinocut/server_tools_ai.py:256`) / `release_checkpoint` (`kinocut/client/quality.py:39`) as the reconciled quality-gate surface, layering the fail-closed publishability derivation on top. The known-limitations + human-review pointers extend `kinocut/workflow/inspector.py` (`inspect_receipt`:60, `_human_review`:269, `_known_limitations`:293). Namespaced CLI adds aliases over the SAME handlers via `CommandRunner.register` (`kinocut/cli/runner.py:20`) and `build_parser` (`kinocut/cli/parser/__init__.py:22`); a central non-TTY output policy extends the current explicit-only `use_json = args.format == "json"` (`kinocut/__main__.py:60`) — the CLI has NO auto non-TTY switch today (confirmed). Capability discovery produces a stable document distinct from `search_tools` (`kinocut/server_tools_basic.py:507`) and `run_diagnostics` (`kinocut/doctor.py:414`). Learning/cost/recipe reports are deterministic projections; the benchmark expands the existing golden/confidence fixtures.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, argparse CLI, pytest 8+ (golden + real-FFmpeg fixtures), Ruff. No new ML core; optional model wording is fail-soft.

## Global Constraints (subset — see index §3)

- `publishable` is derived, never a stored boolean: candidate integrity passes, required artifacts exist + re-hash, no blocking finding unresolved, and the current dependency fingerprint has the required human approval (design §4.9).
- Any protected source/timing/subtitle/graphics/mix/render-param/required-artifact/accepted-limitation change yields a different fingerprint; prior approval becomes inapplicable and the new candidate starts `pending` (design §4.9).
- The human gate is fail-closed: named artifacts + explicit human decision required; automated checks never assert creative taste passed (design §1, §5, coverage #49).
- New namespaced CLI commands call the same handlers as flat aliases; explicit `--format` always overrides auto mode; flat commands preserved (design §3.3, coverage #52–53).
- `CapabilityReport` is stable structured data; it never requires parsing CLI help; `next_action` is a bounded suggestion, never auto-executed (design §4.10).
- Cost is explicit; unknown cost is never inferred as zero; #58 (defect-to-prompt) and #44-style advice stay advisory and unavailable without sufficient evidence (design §4.11, §9).
- MCP/Python/CLI parity; optional-capability fail-soft; no release actions (index §3.6).

## File Structure

### Wave 8 — new production files

- `kinocut/aivideo/review/package.py` — standard `ReviewPackage` manifest assembling inspection artifacts, audio seam report, subtitle QA, technical QA, receipt, known limitations, required checklist, approval state (design §4.8).
- `kinocut/aivideo/review/decision.py` — general `ReviewDecision` (asset/timeline hash, exact range, actor=human, decision enum, rationale, dependency fingerprint) + known-limitation ledger.
- `kinocut/aivideo/review/gate.py` — dependency-fingerprint computation, fail-closed `is_publishable` derivation, invalidation reasons + superseding state.
- Surfaces: `video_review_package`, `video_review_decision`, `video_publish_gate`.

### Wave 9 — new/modified production files

- `kinocut/cli/parser/namespaces.py` — namespace router adding `kino inspect|edit|audio|captions|qa|assets|workflow ...` aliases over existing handlers (flat commands preserved).
- `kinocut/cli/output_policy.py` — central JSON/line output policy; explicit `--format` overrides; agent/non-TTY mode is opt-in and uniform (extends `kinocut/cli/common.py:output_json`).
- `kinocut/aivideo/capability_report.py` — stable `CapabilityReport` builder covering tools, formats, required/optional deps, availability, reason codes, remediation (over `search_tools` + `run_diagnostics` data).
- `kinocut/doctor.py` — additive read-only migration checks (stale registrations/package/env/path/workflow) + remediation text and one bounded `next_action`.
- Surfaces: `video_capabilities`, namespaced CLI aliases, `kino doctor` migration output.

### Wave 10 — new production files

- `kinocut/aivideo/learning/recipe.py` — versioned `WorkflowRecipe` capture (parameter slots, acceptance/review requirements, provenance) + recipe registry over `kinocut/workflow/spec.py`.
- `kinocut/aivideo/learning/cost.py` — append-only `CostEvent` ledger (category/quantity/unit/provenance/confidence; unknown cost explicit) + derived totals.
- `kinocut/aivideo/learning/report.py` — deterministic project learning aggregate + evidence-backed defect-to-prompt rules (#58 advisory, gated).
- `kinocut/aivideo/benchmark/fixtures.py` + `kinocut/aivideo/benchmark/runner.py` — versioned synthetic/redistributable AI-video fixtures, expected findings, receipt/invalidation/duration/subtitle/audio-preservation checks, cross-version result manifest.
- Surfaces: `video_recipe_capture`, `video_cost_ledger`, `video_learning_report`, `video_benchmark_run`.

### New tests

- Wave 8: `tests/test_review_package.py`, `tests/test_review_decision.py`, `tests/test_publish_gate.py`, `tests/test_wave8_surfaces.py`.
- Wave 9: `tests/test_cli_namespaces.py`, `tests/test_cli_output_policy.py`, `tests/test_capability_report.py`, `tests/test_doctor_migrations.py`, `tests/test_wave9_surfaces.py`.
- Wave 10: `tests/test_learning_recipe.py`, `tests/test_cost_ledger.py`, `tests/test_learning_report.py`, `tests/test_aivideo_benchmark.py`, `tests/test_wave10_surfaces.py`.

### Documentation

- `docs/AI_VIDEO_REVIEW.md`, `docs/AI_VIDEO_LEARNING.md`, `docs/AI_VIDEO_BENCHMARK.md`; additive CLI/TOOLS/PYTHON refs. No release entries.

---

## PR 8.1 — Review package and timestamped decisions (#47–48, #50)

### Task 1: Standard review package + integrity + timestamped decisions + limitations

**Files:** Create `kinocut/aivideo/review/package.py`, `kinocut/aivideo/review/decision.py`; Test `tests/test_review_package.py`, `tests/test_review_decision.py`.

**Interfaces:** Consumes Plan 01 inspection artifacts, Plan 02 seam/subtitle/preservation reports, receipts, `kinocut/workflow/inspector.py` (`inspect_receipt`:60, `_human_review`:269, `_known_limitations`:293).

- [ ] **Step 1: Failing tests** — the `ReviewPackage` manifest is deterministic for the same referenced artifacts and references the final candidate, inspection artifacts, audio seam report, subtitle QA, technical QA, receipt, known limitations, checklist, and approval state; each required artifact carries an integrity (re-hash) result; a `ReviewDecision` binds actor=human, decision, exact target/range, rationale, dependency fingerprint; the known-limitation ledger is append-only and bound to finding + artifact hash.
- [ ] **Step 2: RED** → **Step 3: Implement** the manifest + decision + limitation ledger; media bytes not claimed deterministic across FFmpeg builds.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_review_package.py tests/test_review_decision.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(review): standard review package, timestamped decisions, limitation ledger"`.

---

## PR 8.2 — Human gate and approval invalidation (#49, #51)

### Task 2: Dependency fingerprint + fail-closed publishability + invalidation

**Files:** Create `kinocut/aivideo/review/gate.py`; Test `tests/test_publish_gate.py`.

**Interfaces:** Consumes Plan 00 `ApprovalState`, the reconciled `release_checkpoint` surface (server_tools_ai.py:256), existing hash-mismatch precedent (`edl.py:validate_approval_hash`:188, `workflow/executor.py:_step_reusable`:386).

- [ ] **Step 1: Failing tests** — the general dependency fingerprint covers sources, timings, subtitles, mix, params, and render; changing ANY protected dependency class produces a different fingerprint, invalidates prior approval (historical but inapplicable), and starts the new candidate `pending`; `is_publishable` is derived and fails closed when any required artifact is missing/mismatched, any blocking finding is unresolved, or the current fingerprint lacks required human approval; there is no publishable boolean to set directly.
- [ ] **Step 2: RED** → **Step 3: Implement** the fingerprint + derivation + invalidation reasons + superseding state, layered on the reconciled `release_checkpoint` gate.
- [ ] **Step 4: Green (fixtures)** — approval invalidation by EACH protected dependency class (design §8 fixture family).
- [ ] **Step 5: Commit** — `git commit -m "feat(review): fail-closed human gate and approval invalidation"`.

### Task 3: Wave 8 surfaces + gate

**Files:** MCP/CLI/Python for `video_review_package`, `video_review_decision`, `video_publish_gate`; Test `tests/test_wave8_surfaces.py`.

- [ ] Steps: failing parity → RED → implement → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo/review` → leak audit → `git commit -m "feat(review): wave 8 review and approval surfaces"`.

---

## PR 9.1 — Namespaced CLI and non-TTY output policy (#52–53)

### Task 4: Namespace router + central output policy

**Files:** Create `kinocut/cli/parser/namespaces.py`, `kinocut/cli/output_policy.py`; modify `kinocut/cli/parser/__init__.py`, `kinocut/__main__.py`; Test `tests/test_cli_namespaces.py`, `tests/test_cli_output_policy.py`.

**Interfaces:** Consumes `build_parser` (cli/parser/__init__.py:22), `CommandRunner.register` (runner.py:20), `output_json` (common.py:20).

- [ ] **Step 1: Failing tests** — `kino inspect temporal ...` (namespaced) and the flat alias reach the SAME handler with identical output; every existing flat command still parses (backward fixtures); the central output policy switches JSON/line uniformly and an explicit `--format` always overrides; agent/non-TTY mode is opt-in.
- [ ] **Step 2: RED** → **Step 3: Implement** the namespace router as thin aliases (no divergent behavior) + the central policy. Model the alias injection on the data-driven registration already used by `kinocut/cli/parser/postrescue.py` (loops `subparsers.add_parser(command, ...)` over a table); flat registrations live at `kinocut/cli/parser/__init__.py:52–64` and dispatch keys on `args.command`, so aliases map new namespace keys onto the identical handler.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_cli_namespaces.py tests/test_cli_output_policy.py tests/test_cli_parsers.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(cli): namespaced commands and central output policy"`.

---

## PR 9.2 — Capabilities, next action, and migration doctor (#54–56)

### Task 5: Stable capability report + bounded next action + doctor migrations

**Files:** Create `kinocut/aivideo/capability_report.py`; modify `kinocut/doctor.py`; Test `tests/test_capability_report.py`, `tests/test_doctor_migrations.py`.

**Interfaces:** Consumes `search_tools` (server_tools_basic.py:507), `run_diagnostics` (doctor.py:414), Plan 00 `CapabilityReport`/`NextAction`.

- [ ] **Step 1: Failing tests** — `CapabilityReport` is stable structured data (tools, formats, required/optional deps, availability, reason code, remediation) requiring no CLI-help parsing; failures/incomplete reports include at most one bounded `next_action` that is never auto-executed; `run_diagnostics` gains read-only registration/package/env/path/workflow migration checks with remediation text. A concrete first migration check asserts `kinocut`↔`mcp_video` alias/env consistency (the rename is incomplete today: `tests/test_workflow_golden.py` still imports `mcp_video.*`; `_check_crush` reads `MCP_VIDEO_CRUSH_PATH`/`~/.mcp-video/` at doctor.py:239/253) — slotting in as additional `checks.append(_check_*)` calls following the existing `_check_crush`/`_check_audio_engine` shape (doctor.py:434–435).
- [ ] **Step 2: RED** → **Step 3: Implement** the report builder + doctor migration checks (additive, read-only).
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_capability_report.py tests/test_doctor_migrations.py tests/test_doctor.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(cli): capability report, next action, doctor migrations"`.

> **Parallel note:** PR 9.1 and PR 9.2 may run concurrently after their shared contracts land (design §7).

### Task 6: Wave 9 surfaces + gate

**Files:** MCP/Python for `video_capabilities`; Test `tests/test_wave9_surfaces.py`.

- [ ] Steps: failing parity → RED → implement → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut" && ruff check kinocut/cli kinocut/aivideo/capability_report.py` → leak audit → `git commit -m "feat(cli): wave 9 capability surface"`.

---

## PR 10.1 — Recipe, cost, and learning reports (#57–60)

### Task 7: Recipe capture + cost ledger + learning report

**Files:** Create `kinocut/aivideo/learning/{recipe,cost,report}.py`; Test `tests/test_learning_recipe.py`, `tests/test_cost_ledger.py`, `tests/test_learning_report.py`.

**Interfaces:** Consumes `kinocut/workflow/spec.py` versioned specs, Plan 00 `WorkflowRecipe`/`CostEvent`/`PromptOutcome`, Plan 03 registries.

- [ ] **Step 1: Failing tests** — recipe capture records versioned parameter slots + acceptance/review requirements + provenance; the cost ledger is append-only with explicit unknown-cost (never zero-inferred) and derived totals only; the learning report is a deterministic aggregate over verdict/defect/lineage/usage/cost/review ledgers; defect-to-prompt feedback (#58) is rule-based/evidence-first and `capability_unavailable` when evidence is insufficient — model wording may summarize but never alter records.
- [ ] **Step 2: RED** → **Step 3: Implement** the three projections; honesty about missing evidence is mandatory.
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_learning_recipe.py tests/test_cost_ledger.py tests/test_learning_report.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(learning): recipe capture, cost ledger, learning report"`.

---

## PR 10.2 — AI-video acceptance benchmark (#61)

### Task 8: Versioned fixture corpus + cross-version result manifest

**Files:** Create `kinocut/aivideo/benchmark/{fixtures,runner}.py`; Test `tests/test_aivideo_benchmark.py`.

**Interfaces:** Extends the existing SSIM golden suite `tests/test_workflow_golden.py` (`GOLDEN_DIR = tests/fixtures/golden/`, `SSIM_THRESHOLD=0.95`) and the receipt-backed confidence benchmark at `workflows/benchmarks/run_confidence_benchmark.py` (baseline `workflows/05-confidence-baseline/`); reuses the toolchain fingerprint from `versions()` (`kinocut/workflow/_versions.py:48`, returns `{mcp_video, ffmpeg}`) for the cross-version manifest. Note: only two golden media fixtures exist today (`workflow_final.mp4`, `composite.mp4`) — the benchmark adds a versioned AI-video corpus.

- [ ] **Step 1: Failing tests** — versioned synthetic/redistributable fixtures with expected findings; the benchmark verifies receipt shape, approval invalidation, duration safety, subtitle QA, and audio-preservation checks; a cross-version result manifest records outcomes per fixture version.
- [ ] **Step 2: RED** → **Step 3: Implement** the fixture corpus + runner + manifest; fixtures are synthetic/redistributable only (no proprietary media).
- [ ] **Step 4: Green** — `python3 -m pytest -q tests/test_aivideo_benchmark.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(benchmark): versioned ai-video acceptance benchmark"`.

### Task 9: Wave 10 surfaces + full-suite gate

**Files:** MCP/CLI/Python for `video_recipe_capture`, `video_cost_ledger`, `video_learning_report`, `video_benchmark_run`; Test `tests/test_wave10_surfaces.py`.

- [ ] Steps: failing parity → RED → implement → full gate `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/aivideo/learning kinocut/aivideo/benchmark` → leak audit → `git commit -m "feat(learning): wave 10 learning and benchmark surfaces"`.

---

## Wave 8–10 completion criteria

- Review package is deterministic and complete; decisions are timestamped + hash-bound; the human gate is fail-closed and `publishable` is derived, invalidating on any protected-dependency change.
- Namespaced CLI aliases share handlers with flat commands; explicit `--format` overrides; capability report is stable structured data; doctor migration checks are read-only.
- Recipe/cost/learning reports are deterministic and honest about missing evidence; the 61-item acceptance benchmark runs with a cross-version manifest.
- Design §8 fixture families for approval invalidation, interrupted/tampered/changed-spec, and benchmark corpus are exercised; MCP/Python/CLI parity + backward fixtures green; full suite green; canonical import passes; Ruff clean; modules ≤ 800 LOC.
- Independent review approved; no self-approval; no release actions (index §3.6).
- Downstream: Plan 05 gated kernel integration + the program-completion gate consume these surfaces.
