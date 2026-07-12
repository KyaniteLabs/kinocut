# Kinocut AI-Video Program: Implementation Plan Index

**Date:** 2026-07-11
**Status:** planning artifact only — no implementation, version bump, tag, publish, directory submission, deployment, or release is authorized by this document.
**Design source of truth:** [`docs/superpowers/specs/2026-07-10-kinocut-ai-video-editor-design.md`](../specs/2026-07-10-kinocut-ai-video-editor-design.md)
**Coverage source of truth:** [`docs/superpowers/specs/2026-07-10-kinocut-ai-video-backlog-coverage.md`](../specs/2026-07-10-kinocut-ai-video-backlog-coverage.md)
**Field evidence:** [`docs/superpowers/specs/2026-07-10-kinocut-field-wishlist-design.md`](../specs/2026-07-10-kinocut-field-wishlist-design.md)
**Verified master at design time:** `fdbf3483004a8bfd3a1b3c959fdbd1c89dc90bdc`

> **For implementers:** Work in bounded, independently reviewed change units. Steps in the subsystem plans use checkbox (`- [ ]`) syntax for tracking. This index is read-first orientation; it does not itself contain executable steps.

## 1. Purpose

This index translates the approved contract-first AI-video editor design into a set of six dependency-ordered subsystem implementation plans plus this index. It exists so that any worker can pick up exactly one plan, know its upstream dependencies, its owned files, its failing-test entry point, its merge position, and the hard stop before release.

It does **not** re-argue the design. Alternatives (one-command-per-item, kernel-first rewrite) were considered and rejected in design §2. This index binds the design's Wave 0–10 and the gated kernel wave to concrete plan files and to the 61-item coverage matrix, and it records the single program-completion gate and the single release boundary that govern all six plans.

## 2. The seven-document set

| Doc | File | Design scope | Program work unit(s) |
|---|---|---|---|
| Index | `2026-07-11-kinocut-ai-video-plan-index.md` (this file) | Cross-cutting: constraints, merge order, 61-item map, completion gate | `G002` |
| 00 | [`2026-07-11-kinocut-ai-video-00-foundation.md`](2026-07-11-kinocut-ai-video-00-foundation.md) | Wave 0 — canonical records, private store, receipt/capability contracts | `G003` |
| 01 | [`2026-07-11-kinocut-ai-video-01-safety-and-inspection.md`](2026-07-11-kinocut-ai-video-01-safety-and-inspection.md) | Wave 1 field safety + Wave 2 ingest & temporal inspection | `G004`, `G005` |
| 02 | [`2026-07-11-kinocut-ai-video-02-salvage-audio-subtitles.md`](2026-07-11-kinocut-ai-video-02-salvage-audio-subtitles.md) | Wave 3 verdict/protection/salvage + Wave 4 audio continuity + Wave 5 subtitle/graphics QA | `G006`, `G007`, `G008` |
| 03 | [`2026-07-11-kinocut-ai-video-03-asset-intelligence-and-planning.md`](2026-07-11-kinocut-ai-video-03-asset-intelligence-and-planning.md) | Wave 6 asset intelligence + Wave 7 editorial planning & continuity | `G009`, `G010` |
| 04 | [`2026-07-11-kinocut-ai-video-04-review-cli-learning.md`](2026-07-11-kinocut-ai-video-04-review-cli-learning.md) | Wave 8 review/approval + Wave 9 CLI/agent ergonomics + Wave 10 learning & benchmark | `G011`, `G012`, `G013` |
| 05 | [`2026-07-11-kinocut-ai-video-05-gated-kernel-integration.md`](2026-07-11-kinocut-ai-video-05-gated-kernel-integration.md) | Kernel wave K.1 (gated) + program stop-before-release | `G014`, and `G015` handoff |

## 3. Global constraints (apply to every subsystem plan)

These are lifted verbatim in intent from design §3, §8, §9, §10 and `AGENTS.md`. Each subsystem plan restates the subset it must honor; none may weaken them.

### 3.1 Canonical vs derived state (design §3.1)

- Canonical project state is only versioned append-only records: acceptance specs, immutable asset records + lineage, clip verdicts, defect findings, protected elements, limitations, review decisions/approval states, and learning events (prompt outcomes, usage, costs, recipes).
- Indexes, coverage reports, review packages, learning reports, recommendations, and benchmark summaries are **derived and rebuildable**. They may never silently become independent sources of truth.

### 3.2 Storage and privacy (design §3.2)

- Project layout: caller-selected `project/` with private `project/.kinocut/` holding `assets/sha256/<digest>/`, `records/<kind>.jsonl`, `receipts/`, `artifacts/`, `indexes/`, `locks/`.
- Ingest copies bytes into the content-addressed store **before** any normalization/repair; `asset_id = sha256:<64 lowercase hex>` of original bytes is the stable identity; filenames are labels only. Ingest is idempotent by digest.
- Records are append-only; corrections **supersede** by ID and never rewrite history. Writes use a project lock + atomic temp-file replacement; a failed write leaves the last valid record intact.
- Public receipts contain project-relative paths, IDs, and hashes only — never home paths, usernames, raw prompts (by default), credentials, or environment dumps. Raw prompts and rights evidence are private records; public exports expose opt-in summaries or hashes.
- Cross-project reuse is explicit and human-authorized (a configured local library of signed/snapshotted approved records); Kinocut never scans unrelated directories automatically. Stale/missing origins are reported, not silently treated as current approval.

### 3.3 Compatibility (design §3.3, `AGENTS.md`)

- Existing MCP tool names, Python client methods, flat CLI commands, argument defaults, and result fields remain valid. New fields are additive; existing receipt readers keep accepting older kinds/versions.
- New namespaced CLI commands call the **same** handlers as compatibility aliases; no divergent behavior.
- Public capabilities keep MCP + Python + CLI parity unless explicitly classified as an internal record API.
- Optional ML dependencies fail soft with a typed `capability_unavailable` finding; deterministic inspection and human review stay usable.
- Verify canonical import after every change: `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"`.

### 3.4 FFmpeg security and error handling (`AGENTS.md`, design §9)

- All user-controlled values in FFmpeg filter strings MUST be escaped with `_escape_ffmpeg_filter_value()` from `kinocut/ffmpeg_helpers.py`. Never f-string user values into filter strings.
- Raise only custom errors from `kinocut/errors.py` (`InputFileError`, `ProcessingError`, `MCPVideoError` with `error_type="validation_error"`); never raw `ValueError`/`RuntimeError`/`FileNotFoundError`; never embed `result.stderr` directly (route through `ProcessingError`, which truncates to 500 chars).
- Every `subprocess.run`/`Popen` has a `timeout` (`DEFAULT_FFMPEG_TIMEOUT` from `kinocut/defaults.py`); catch `TimeoutExpired`; validate paths with `_validate_input_path()`.
- All defaults in `defaults.py`, validation constants in `validation.py`, limits in `limits.py` — reference by name, never hardcode magic numbers.
- Module ≤ 800 LOC (split into a subpackage otherwise); function ≤ 80 lines; no dead code.

### 3.5 TDD and review discipline (design §8)

Every PR is one coherent change unit, starts from current master in its own worktree, follows red-green-refactor, and before commit/PR:

- Writes the failing regression/contract test first and captures the RED result.
- Adds unit tests for strict validation, canonical hashes, migrations, privacy, typed errors.
- Adds real-FFmpeg integration tests for media behavior; mocks only for unavailable external/ML providers.
- Proves MCP + Python client + CLI handler + public-surface parity for each public feature, plus backward fixtures for flat aliases and legacy receipt shapes.
- Runs `python3 -m pytest tests/ -x -q --tb=short`, `python3 -c "import kinocut"`, and CI-required Ruff/type checks.
- Runs a public leak audit before commit/issue/push/PR.
- Uses independent author/reviewer roles; the author does not self-approve.

### 3.6 Release boundary (design §10) — NON-NEGOTIABLE

Implementation, test commits, issue receipts, and dependency-ordered PRs are authorized only after written-spec review. The following remain separately prohibited across **all** plans: version bump; git tag or release branch; package upload; MCP/directory submission; deployment; release creation or announcement. After the final implementation wave, stop and deliver the final coverage matrix, test + leak-audit receipts, known limitations, optional/deferred capability state, and human-review checklist, then wait for explicit release authorization. Plan 05 owns this stop.

## 4. Dependency-ordered merge sequence

The design's PR waves compose the strict order below. Wave 0 is the sole hard prerequisite for everything; after it merges, several pairs run concurrently in isolated worktrees. Controller-owned merge points (receipt schema, public-surface manifests, shared defaults, central capability registry) are never edited concurrently without an assigned integration slice (design §7).

```text
PR 0.1  canonical records + private store         (Plan 00)  ── blocks all
PR 0.2  receipt + capability contracts            (Plan 00)  ── blocks all surfaces
   ├─ PR 1.1 loss-proof add-audio                 (Plan 01)  ┐ parallel after 0.2
   ├─ PR 1.2 ASS + dimension-aware subtitle burn  (Plan 01)  │ (disjoint engines)
   ├─ PR 2.1 ingest + immutable + preflight        (Plan 01)  │
   └─ PR 2.2 temporal evidence package            (Plan 01)  ┘
PR 2.3  deterministic temporal defect checks      (Plan 01)  after 2.2
PR 2.4  optional visual findings providers        (Plan 01)  after 2.2/2.3
PR 3.1  editorial verdict + defect workflow       (Plan 02)  after 0.1, 2.x
   ├─ PR 3.2 body swap + audio preservation proof (Plan 02)  ┐ 3.2/3.3 parallel
   └─ PR 3.3 salvage derivatives                  (Plan 02)  ┘
   ├─ PR 4.1 one-shot audio bed + audition        (Plan 02)  ┐ 4.1/5.1 parallel
   └─ PR 5.1 subtitle temporal + safe-area QA     (Plan 02)  ┘
PR 4.2  voice seam metrics + report               (Plan 02)  after 4.1
PR 5.2  deterministic graphics recipe             (Plan 02)  after 0.1
PR 6.1  approved clip + bed registries            (Plan 03)  after 3.1
   ├─ PR 6.2 semantic + near-duplicate retrieval  (Plan 03)  ┐ 6.2/6.3 parallel
   └─ PR 6.3 prompt outcome memory                (Plan 03)  ┘
PR 7.1  beat map + coverage + continuity plan     (Plan 03)  after 6.1
PR 7.2  continuity evidence + regen advice        (Plan 03)  after 7.1 (#44 gated on data)
PR 7.3  variant contract integration             (Plan 03)  after 7.1
PR 8.1  review package + timestamped decisions    (Plan 04)  after 2.x, 3.1, 7.1
PR 8.2  human gate + approval invalidation        (Plan 04)  after 8.1
   ├─ PR 9.1 namespaced CLI + non-TTY output      (Plan 04)  ┐ 9.1/9.2 parallel
   └─ PR 9.2 capabilities + next action + doctor  (Plan 04)  ┘ after their contracts
PR 10.1 recipe + cost + learning reports          (Plan 04)  after 6.x, 8.x
PR 10.2 AI-video acceptance benchmark             (Plan 04)  after all feature waves
PR K.1  protected timeline regions + stage reuse  (Plan 05)  GATED: after human kernel-gate reconciliation only
```

## 5. 61-item coverage → owning plan / PR

Item numbers are from the coverage matrix. Class codes: AE already-exists, EE extend-existing, NP new-primitive, CO composition, OC optional-capability, DF defer.

| # | Capability | Class | Owning PR | Plan |
|---:|---|:--:|---|:--:|
| 1 | Generation Acceptance Spec | NP | 0.1 / 3.1 | 00 / 02 |
| 2 | AI Asset Ingest | EE | 2.1 | 01 |
| 3 | Immutable Source Preservation | EE | 2.1 | 01 |
| 4 | Media Preflight | EE | 2.1 | 01 |
| 5 | Explicit Clip Verdicts | NP | 3.1 | 02 |
| 6 | Defect Taxonomy | NP | 0.1 / 3.1 | 00 / 02 |
| 7 | Approved-Element Locking | NP | 0.1 / 3.1 | 00 / 02 |
| 8 | Receipt-Backed Editing | EE | 0.2 / 1.1 | 00 / 01 |
| 9 | Motion Strip | CO | 2.2 | 01 |
| 10 | Late-Frame QA | CO | 2.2 | 01 |
| 11 | Text-Drift Check | CO | 2.2 | 01 |
| 12 | Temporal Inspect | CO | 2.2 | 01 |
| 13 | Loop Integrity Check | NP | 2.3 | 01 |
| 14 | Frozen/Black/Corrupt Detection | EE | 2.3 | 01 |
| 15 | Motion Intent Check | OC | 2.4 | 01 |
| 16 | Generative Defect Report | OC | 2.3 / 2.4 | 01 |
| 17 | Body Swap | NP | 3.2 | 02 |
| 18 | Salvage Clip | EE | 3.3 | 02 |
| 19 | Continuity Assistant | OC | 7.2 | 03 |
| 20 | Approved Clip Reuse | EE | 6.1 | 03 |
| 21 | Protected Timeline Regions | DF | K.1 | 05 |
| 22 | Resume-Aware Rendering | EE | K.1 | 05 |
| 23 | Audio Bed | EE | 4.1 | 02 |
| 24 | Bed Audition | CO | 4.1 | 02 |
| 25 | Voice Style Check | OC | 4.2 | 02 |
| 26 | Voice Identity Check | OC | 4.2 | 02 |
| 27 | ASR Timestamp Clamp | EE | 1.2 / 4.2 | 01 / 02 |
| 28 | Audio Preservation Verification | EE | 0.2 / 3.2 | 00 / 02 |
| 29 | Audio Duration Safety | EE | 1.1 | 01 |
| 30 | Audio Seam Report | CO | 4.2 | 02 |
| 31 | ASS Subtitle Support | EE | 1.2 | 01 |
| 32 | Dimension-Aware SRT/VTT Rendering | EE | 1.2 | 01 |
| 33 | Subtitle Safe-Area Check | NP | 5.1 | 02 |
| 34 | Subtitle Temporal QA | EE | 5.1 | 02 |
| 35 | Deterministic Graphics Layer | CO | 5.2 | 02 |
| 36 | Clip Index | EE | 0.1 / 6.1 | 00 / 03 |
| 37 | Semantic Clip Search | EE | 6.2 | 03 |
| 38 | Generation Lineage | EE | 2.1 / 6.1 | 01 / 03 |
| 39 | Duplicate/Near-Duplicate Detection | OC | 6.2 | 03 |
| 40 | Prompt Outcome Memory | NP | 6.3 | 03 |
| 41 | Reusable Bed Registry | NP | 6.1 | 03 |
| 42 | Semantic Beat Map | EE | 7.1 | 03 |
| 43 | Coverage Report | CO | 7.1 | 03 |
| 44 | Regeneration Decision Assistant | DF | 7.2 | 03 |
| 45 | Continuity Plan | NP | 7.1 | 03 |
| 46 | Variant-Aware Timeline | AE | 7.3 | 03 |
| 47 | AI-Video Review Package | CO | 0.2 / 8.1 | 00 / 04 |
| 48 | Timestamped Review Decisions | EE | 8.1 | 04 |
| 49 | Human Review Gate | EE | 8.2 | 04 |
| 50 | Known-Limitation Ledger | EE | 8.1 | 04 |
| 51 | Approval Invalidation | EE | 0.2 / 8.2 | 00 / 04 |
| 52 | Namespaced CLI | NP | 9.1 | 04 |
| 53 | Agent-Mode Output | EE | 9.1 | 04 |
| 54 | Capability Discovery | EE | 0.2 / 9.2 | 00 / 04 |
| 55 | Recommended Next Action | NP | 0.2 / 9.2 | 00 / 04 |
| 56 | Doctor Migrations | EE | 9.2 | 04 |
| 57 | Project Learning Report | CO | 10.1 | 04 |
| 58 | Defect-to-Prompt Feedback | DF | 10.1 | 04 |
| 59 | Workflow Recipe Capture | EE | 10.1 | 04 |
| 60 | Production Cost Ledger | NP | 10.1 | 04 |
| 61 | Acceptance Benchmark | EE | 10.2 | 04 |

## 6. Program completion gate (design §8)

The program is implementation-complete **only** when:

1. Every one of the 61 rows has a merged owner **or** an explicitly exercised unavailable/deferred contract (deferred: #21 until kernel gate; #44 until cost/outcome data exists; #58 until enough linked prompt outcomes exist).
2. The final coverage matrix links every item to code, tests, and receipts.
3. The full supported FFmpeg/platform matrix is green.
4. An independent review package is approved by a human.

This gate is owned by ultragoal `G015` and is described operationally in Plan 05. No plan may declare the program done before this gate; no plan may cross the release boundary in §3.6.

## 7. How to use these plans

- Implement in the merge order of §4. Do not start a dependent wave before its prerequisite has merged and its branch/worktree is deleted.
- Each subsystem plan is self-contained: it lists new/modified files, per-PR TDD tasks with exact failing tests, run commands, expected RED output, and a commit step.
- When the coverage map (§5) shows an item split across two PRs (e.g. #8 across 0.2 and 1.1), the earlier PR lands the contract/field and the later PR lands the behavior; neither is complete alone.
- Deferred/optional items must ship their typed unavailable contract and a test proving fail-soft behavior, never a silent omission.
- This index and the six subsystem plans are the only artifacts produced under `G002`. They are documentation; producing them authorizes no code change.
