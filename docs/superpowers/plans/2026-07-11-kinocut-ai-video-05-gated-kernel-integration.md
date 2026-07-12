# Plan 05 — Gated Kernel Integration (K.1) + Program Stop-Before-Release

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change. This plan is EXPLICITLY GATED (see §Gate) and owns the program STOP before release (index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §6 "Kernel integration wave", §8 program completion gate, §10 release boundary; coverage #21 (DF), #22 (EE).
**Kernel dependency (separately owned):** [`docs/plans/2026-07-09-kinocut-trusted-execution-layer.md`](../../plans/2026-07-09-kinocut-trusted-execution-layer.md) — APPROVED, Phase 0 in progress; all post-Phase-0 engineering is `blocked:post-release`.

> **For implementers:** Do not begin any step in this plan until the gate below is satisfied by an explicit human act. Work task-by-task in bounded branches with independent review.

**Goal:** Once the durable editing kernel exists and its human gate is reconciled, make protected timeline regions durable (compile Plan 00 `ProtectedElement`s into kernel project revisions) and extend the kernel's hash-resume into changed-revision stage reuse — WITHOUT creating a parallel project, revision, or resume system — then stop the program before any release with the final evidence package and human-review checklist.

**Architecture:** This wave is an integration layer over the planned kernel, not a new subsystem. The kernel plan introduces `kinocut/kernel/project.py` (durable edit project + append-only linear revision snapshots), `kinocut/kernel/render_jobs.py` / `kernel/runner.py` (async render), `kinocut/kernel/cas.py` (content-addressed store), and `kinocut/kernel/events.py`, with `docs/adr/0008-editing-kernel.md` naming the kernel nouns. Crucially, the kernel **wraps** the shipped `video_workflow_*` engine and **reuses** its spec-hash + per-step-hash resume cursor (`kinocut/workflow/executor.py:render_workflow`:68, `_load_resume`:342, `_step_reusable`:386) rather than inventing a second resume mechanism. K.1 therefore:

1. Reconciles the existing human gate — the AI-video program's fail-closed human review gate (Plan 04 PR 8.2, `kinocut/aivideo/review/gate.py`) and the kernel's Phase-0 `blocked:post-release` gate — into ONE explicit reconciliation recorded in an ADR, so there is a single human-authorized entry point, not two competing gates.
2. Compiles `ProtectedElement`s of `element_type = "timeline range"` (Plan 00 `kinocut/contracts/protection.py`) into durable protected ranges on kernel project revisions (`kinocut/kernel/project.py`), so protection survives across sessions (#21, currently deferred — DF).
3. Extends the kernel's changed-revision reuse: where the shipped resume reuses completed steps of the SAME spec, K.1 reuses unchanged stages across a CHANGED revision by fingerprint, completing #22 (EE) on the kernel — reusing the existing per-step-hash cursor, never a parallel resume.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, the planned `kinocut/kernel/*` modules, the existing workflow resume cursor, pytest 8+ real-media fixtures, Ruff. No new FFmpeg surface beyond what the kernel already runs.

## Gate — this plan may not start until ALL are true

- [ ] The kernel plan's **Phase 0 has exited** and Phase 1 durable-kernel corners (`kinocut/kernel/project.py` durable edit project + revisions, async render/resume, receipt lineage) are merged and green — K.1 has no durable project/revision store to attach to otherwise.
- [ ] A **human has explicitly removed the `blocked:post-release` gate** for this integration (the kernel plan requires labels be removed phase-by-phase by explicit human act).
- [ ] The AI-video program Waves 0–10 (Plans 00–04) are merged, and the fail-closed human gate (Plan 04 PR 8.2) exists so its reconciliation with the kernel gate is possible.
- [ ] An **ADR reconciling the two human gates** is authored and human-approved (see PR K.1 Task 1).
- [ ] The written-spec review required by the design (§10) is complete.

If any box is unchecked, STOP and escalate — there is no force path (design §4.6). No parallel project/revision/resume store may be created to work around a missing kernel (design §6, §11).

## Global Constraints (subset — see index §3)

- No parallel project, revision, or resume system — reuse the kernel's project store and the shipped workflow resume cursor (design §6 kernel wave; kernel plan P1.2 "reuses the existing workflow resume cursor rather than inventing a second resume mechanism").
- Protected-timeline-region changes fail closed with `protected_element_change` unless a new explicit human review authorizes them; no force flag (design §4.6).
- Any protected source/timing/subtitle/graphics/mix/render-param/artifact change yields a new approval fingerprint; prior approval becomes inapplicable (design §4.9).
- Release boundary is absolute: after this wave, STOP — no version bump, tag, publish, submission, deploy, or release (index §3.6, design §10).
- MCP/Python/CLI parity; additive compatibility; independent review; no self-approval (design §8).

## File Structure

### New production files (PR K.1) — all under the kernel's existing package

- `kinocut/kernel/protected_regions.py` — compile `ProtectedElement(timeline range)` into durable protected ranges on the current kernel revision; a mutation precheck over the kernel revision's touched-node set that fails `protected_element_change`. Wraps Plan 02's `kinocut/aivideo/protection.py:assert_no_protected_collision` at the durable-revision level.
- `kinocut/kernel/revision_reuse.py` — changed-revision stage reuse: fingerprint each stage of a revision, and when a new revision changes only some stages, reuse the unchanged ones via the existing per-step-hash cursor (extends, does not replace, `workflow/executor.py:_step_reusable`).

### Modified production files

- `kinocut/kernel/project.py` — record protected ranges on append-only revisions (additive field; no revision-history rewrite).
- `docs/adr/0008-editing-kernel.md` (or a new `docs/adr/0009-ai-video-gate-reconciliation.md`) — record the single reconciled human gate.
- Receipt lineage (kernel-owned) — carry `protected_region_ids` + `reused_revision_stages` additively (controller-owned merge point; coordinate before editing).

### New tests

- `tests/test_kernel_protected_regions.py`, `tests/test_kernel_revision_reuse.py`, `tests/test_kernel_gate_reconciliation.py`, `tests/test_kernel_integration_surfaces.py`.

### Documentation

- Update `docs/AI_VIDEO_REVIEW.md` + the kernel ADR; `docs/AI_VIDEO_PROGRAM_EVIDENCE.md` (the final coverage matrix + human-review checklist for the program STOP). No CHANGELOG/release entry.

---

## PR K.1 — Protected timeline regions and changed-stage reuse (#21, #22)

### Task 1: Reconcile the existing human gate (ADR + failing reconciliation test)

**Files:** Author `docs/adr/0009-ai-video-gate-reconciliation.md`; Create `tests/test_kernel_gate_reconciliation.py`.

**Interfaces:** Consumes Plan 04 `kinocut/aivideo/review/gate.py` (fail-closed publishability) and the kernel's human gate; the kernel ADR `docs/adr/0008-editing-kernel.md`.

- [ ] **Step 1: Author the reconciliation ADR** — record that the AI-video fail-closed publishability gate and the kernel's post-release human gate resolve to ONE human-authorized entry point; no second gate; no force path. Human approval of the ADR is a prerequisite (Gate).
- [ ] **Step 2: Write the failing test** — asserting there is exactly one publish authority: a kernel revision cannot be marked publishable except through the reconciled gate; attempting to publish via a kernel path that bypasses the AI-video gate fails closed.

```python
def test_single_reconciled_publish_authority(kernel_project):
    rev = make_revision(kernel_project)
    with pytest.raises(MCPVideoError) as e:
        kernel_publish_bypassing_ai_video_gate(rev)
    assert e.value.code in {"protected_element_change","validation_error"}
```

- [ ] **Step 3: RED** — `python3 -m pytest -q tests/test_kernel_gate_reconciliation.py` → import/behavior error.
- [ ] **Step 4: Implement** the single reconciled authority (route kernel publish through Plan 04's gate).
- [ ] **Step 5: Green + commit** — `python3 -m pytest -q tests/test_kernel_gate_reconciliation.py && git commit -m "feat(kernel): reconcile ai-video and kernel human gates"`.

### Task 2: Durable protected timeline regions (#21)

**Files:** Create `kinocut/kernel/protected_regions.py`; modify `kinocut/kernel/project.py`; Test `tests/test_kernel_protected_regions.py`.

**Interfaces:** Consumes Plan 00 `ProtectedElement` (`kinocut/contracts/protection.py`), Plan 02 `assert_no_protected_collision` (`kinocut/aivideo/protection.py`), the kernel revision store (`kinocut/kernel/project.py`).

- [ ] **Step 1: Failing tests** — a `ProtectedElement(element_type="timeline range")` compiles into a durable protected range on the current kernel revision and persists across sessions; a mutating op whose touched node set collides with a protected range fails `protected_element_change` unless a new explicit human decision authorizes it; the protected range is recorded on the append-only revision without rewriting revision history; no force flag exists.
- [ ] **Step 2: RED** → **Step 3: Implement** the compile + durable precheck at the revision level, reusing Plan 02's precheck logic; additive revision field only.
- [ ] **Step 4: Green (fixtures)** — cross-session protection, collision rejection, authorized override via new human decision.
- [ ] **Step 5: Commit** — `git commit -m "feat(kernel): durable protected timeline regions"`.

### Task 3: Changed-revision stage reuse (#22)

**Files:** Create `kinocut/kernel/revision_reuse.py`; Test `tests/test_kernel_revision_reuse.py`.

**Interfaces:** Extends `kinocut/workflow/executor.py:_step_reusable` (:386) and `_load_resume` (:342) semantics; consumes kernel revisions.

- [ ] **Step 1: Failing tests** — given revision N and a derived revision N+1 that changes only some stages, rendering N+1 reuses the unchanged stages by fingerprint (asserted via a spy that the reused stages are NOT re-executed) and re-runs only changed stages and everything downstream; a tampered/mismatched reused intermediate fails closed (reusing the existing hash-mismatch precedent, not a new one).
- [ ] **Step 2: RED** → **Step 3: Implement** changed-revision reuse strictly on top of the existing per-step-hash cursor. The specific blocker to work around is the whole-file `spec_hash` equality gate in `_load_resume` (executor.py:355–360, `RESUME_SPEC_MISMATCH` — "a changed spec is a different job"): changed-revision reuse must key on per-stage identity (op params + input digests, i.e. the kernel CAS cache-key model), NOT the whole-spec hash, while still delegating actual stage reuse to `_step_reusable`. Do NOT introduce a second resume mechanism or a render DAG (the full render DAG is deferred to the kernel plan's Phase 3 P3.0 — K.1 reuses linear-revision stages only, wrapping `render_submit` exactly as the kernel plan specifies).
- [ ] **Step 4: Green (fixtures)** — changed-spec/changed-revision reuse, tampered-intermediate rejection (design §8 fixture family).
- [ ] **Step 5: Commit** — `git commit -m "feat(kernel): changed-revision stage reuse over existing resume cursor"`.

### Task 4: Integration surfaces + full-suite gate

**Files:** MCP/CLI/Python surfaces for protected-region declaration + changed-revision render (thin, over kernel); Test `tests/test_kernel_integration_surfaces.py`.

- [ ] **Step 1: Failing parity tests** across MCP/Python/CLI; existing `video_workflow_*` callers see no behavior change (kernel wraps, never breaks them).
- [ ] **Step 2: RED** → **Step 3: Implement** surfaces using the `@mcp.tool()`/`@_safe_tool`/`_result` + `CommandRunner.register` pattern.
- [ ] **Step 4: Full gate** — `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/kernel`.
- [ ] **Step 5: Leak audit + commit** — `git commit -m "feat(kernel): protected-region and changed-revision surfaces"`.

---

## Program STOP-before-release (hands off to G015)

After K.1 merges, the program is at the boundary of design §10. This plan owns the stop.

### Task 5: Assemble the final program evidence package

**Files:** `docs/AI_VIDEO_PROGRAM_EVIDENCE.md`.

- [ ] **Step 1: 61-item evidence matrix** — every coverage item links to merged code, tests, and receipts, OR to an explicitly exercised unavailable/deferred contract (deferred: #21 now landed via K.1; #44 until cost/outcome data; #58 until enough linked prompt outcomes). Cross-check against the index §5 map.
- [ ] **Step 2: Full supported verification** — record `python3 -m pytest tests/ -x -q --tb=short`, `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"`, Ruff/type checks, and the full supported FFmpeg/platform matrix as green.
- [ ] **Step 3: Public leak audit** across all receipts, issue bodies, and exports (no home paths, usernames, prompts, credentials, env dumps).
- [ ] **Step 4: AI-slop cleanup + architecture-invariant proof** — canonical-vs-derived state honored, no parallel stores, no force flags, `publishable` derived-only, optional providers fail-soft.
- [ ] **Step 5: Independent review** — code-reviewer + architect approval by a human; author did not self-approve.
- [ ] **Step 6: Human-review checklist** — the named artifacts and explicit human decisions still required before any release.

### Task 6: STOP

- [ ] Confirm the program completion gate (index §6) is met: all 61 rows owned/deferred, matrix links complete, supported matrix green, independent review approved.
- [ ] **STOP.** Do not version bump, tag, create a release branch, upload a package, submit to any MCP/directory, deploy, or announce (index §3.6, design §10). Deliver the evidence package + human-review checklist and WAIT for explicit release authorization. This is a hard stop, not a checkpoint to pass through.

---

## Completion criteria (this plan)

- The Gate is satisfied by explicit human acts before any implementation begins; otherwise the plan does not start.
- Protected timeline regions are durable on kernel revisions and fail closed on collision; changed-revision stage reuse works over the EXISTING resume cursor with no parallel system; #21 and #22 are complete on the kernel.
- No parallel project/revision/resume store was created; existing `video_workflow_*` behavior is unchanged; the two human gates are reconciled into one.
- The final 61-item evidence matrix, verification receipts, leak audit, architecture-invariant proof, and human-review checklist are assembled.
- Independent review approved; no self-approval; the program STOPS before release and waits for explicit authorization.
