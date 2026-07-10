# mcp-video 1.6.0 — Release Trust Packet

> **Historical pre-rescue packet.** This packet captures the 2026-07-09 workflow/compositor
> candidate before the dedicated rescue and post-rescue work landed. The current 1.6.0
> release evidence, counts, scope, and residual risks are in
> [`RESCUE_POST_RESCUE_RECEIPT.md`](RESCUE_POST_RESCUE_RECEIPT.md). Where the two differ, the
> current receipt is authoritative.

Story 9 of the 1.6.0 release (RALPLAN-DR consensus plan §8). This packet records every
release gate with its exact command and tail output, the fresh smoke evidence generated on
novel inputs, the leak audit, residual risks and deferrals, and the reproducibility note.

- Release: **1.6.0** (SemVer MINOR — additive only: +4 tools, +4 CLI, additive compositor
  semantics, `layer_plan` receipt v2, new error codes). Not tagged, not pushed, not
  published — release execution is deferred to the maintainer.
- Date generated: 2026-07-09
- Worktree branch: `worktree-story9-trust` (base `635b979` = all eight prior stories)
- FFmpeg: 8.1 (`/opt/homebrew/bin/ffmpeg`) · Python: 3.14.5 · venv: `.venv`

---

## 1. Gate results (exact command + tail)

All commands run from the worktree root against the committed 1.6.0 state.

### 1.1 Full test suite (zero failures)
```
$ .venv/bin/python -m pytest tests/ -q
...
1867 passed, 15 skipped, 8 warnings in 216.98s (0:03:36)
```
**PASS** — 0 failed. (Count moved 1824 → **1867** by the pre-release hardening round's +43
regression tests — see §8.) (The 8 warnings are intentional guardrail `UserWarning`s asserted by
tier-1 regression tests, not failures.) The plan's `-x` gate command
(`pytest tests/ -x -q --tb=short`) is a strict subset of this full run and therefore also
passes.

### 1.2 Import smoke
```
$ .venv/bin/python -c "import mcp_video; print('import OK, version', mcp_video.__version__)"
import OK, version 1.6.0
```
**PASS**

### 1.3 Diff hygiene
```
$ git diff --check
clean
```
**PASS** — no whitespace/conflict markers.

### 1.4 Lint (ruff, whole repo)
```
$ .venv/bin/ruff check .
All checks passed!
```
**PASS**

### 1.5 Package build (sdist + wheel)
```
$ .venv/bin/python -m build --sdist --wheel
...
Successfully built mcp_video-1.6.0.tar.gz and mcp_video-1.6.0-py3-none-any.whl
```
**PASS** — artifacts: `dist/mcp_video-1.6.0.tar.gz` (323 KB), `dist/mcp_video-1.6.0-py3-none-any.whl` (402 KB). (`dist/` is git-ignored and not committed.)

### 1.6 Distribution metadata check (twine)
```
$ .venv/bin/twine check dist/*
Checking dist/mcp_video-1.6.0-py3-none-any.whl: PASSED
Checking dist/mcp_video-1.6.0.tar.gz: PASSED
```
**PASS** — `twine` available in venv.

### 1.7 Repository readiness audit
```
$ .venv/bin/python scripts/repo-readiness-audit.py
...
PASS Project version is set in pyproject
PASS pyproject version matches mcp_video.__version__
...
PASS At least one git tag exists
== Result ==
WARNINGS: 2
- Working tree has uncommitted changes
- Current branch has no upstream configured
Repository readiness baseline passed.
```
**PASS** — both warnings are expected pre-commit/pre-push state (the audit ran while the
packet was still uncommitted; the branch is deliberately not pushed).

### 1.8 Receipt privacy suite
```
$ .venv/bin/python -m pytest tests/test_receipt_privacy.py -q
4 passed in 0.80s
```
**PASS** — scans committed docs/examples plus freshly produced workflow dry-run/render
artifacts and a composite dry-run layer_plan for home paths, usernames-in-paths, and
secret-shaped tokens.

### 1.9 Public-site identity parity (test-enforced version pin)
```
$ .venv/bin/python -m pytest tests/test_public_surface.py::test_public_site_matches_release_identity -q
1 passed in 0.16s
```
**PASS** — `index.html` at `"version": "1.6.0"` / `v1.6.0`, and the proven-test-count claim
at `1,800+`, are now enforced green.

---

## 2. Suite count evolution & drift counts

| Metric | Pre-release baseline | Post-stories (pre-hardening) | Final (post-hardening, measured) |
|---|---|---|---|
| pytest passed | 1607 (documented in plan §8) | 1824 | **1867** (+43 hardening tests, §8) |
| pytest skipped | 15 | 15 | **15** |
| pytest failed | 0 | 0 | **0** |
| MCP tools (drift manifest) | 120 | 124 | **124** (+4 `video_workflow_*`; hardening added no tools) |
| CLI commands (drift manifest) | 99 | 103 | **103** (+4 flat `workflow-*`; hardening added no commands) |

The public-site test-count claim was moved `1,600+` → `1,800+` — a floor the suite proves
(1824 passing). Drift counts 124/103 are asserted in `tests/test_public_surface.py`
(`len(tool_names) == 124` in both the registry and real-stdio-boot tests; `len(EXPECTED_CLI_COMMANDS) == 103`).

Note on the 1607 baseline: this is the plan-documented pre-release figure, not re-measured
in this worktree (the pre-Story-1 tree is not checked out here). The final 1824 is measured.

---

## 3. Release-branch commits (`git log --oneline 3c46799..HEAD`)

`3c46799` (`feat: expand composite-layers capabilities`) is the pre-release baseline.

```
9459ad2 chore: release 1.6.0 — version bump across identity surfaces
25557ce fix: keep composite layer-plan output path workspace-relative
635b979 test: add receipt privacy scan
5cf57c0 docs: document workflow engine and compositor upgrades across public surfaces
6e8bbf0 feat: add workflow batch variants and keep-intermediates override
91529f1 feat: add workflow resume and receipt inspection
d14d5d0 feat: add rotation and pivot to composite-layers
97574ae feat: add workflow render executor with receipts (video_workflow_render)
ada1211 feat: add full-canvas blend modes to composite-layers
29b2180 feat: add workflow dry-run planner (video_workflow_plan)
091cd01 feat: expose video_workflow_validate across MCP/CLI/Python
15817cf feat: add workflow job-spec model and fail-closed validator
```
The `docs: add 1.6.0 release trust packet with smoke evidence` commit that carries this
packet lands immediately after `9459ad2` and is therefore not self-referenced above.

---

## 4. Smoke evidence (fresh, novel inputs, `smoke/`)

Generated by a one-off script that creates all media fresh with FFmpeg and seeds every run
with a novel token so nothing hits a cache. All receipts are workspace-relative. See
`smoke/SMOKE_LOG.md` for the run log.

| # | Artifact | What it proves |
|---|---|---|
| a | `smoke/workflow_render_receipt.json` | Real 4-step E2E render (probe→trim→resize→add_text), novel params. All steps `completed`; receipt carries `versions.mcp_video: 1.6.0`, per-step input/output hashes, cleanup manifest (`policy: clean-on-success`, `cleaned: true`), determinism caveat. |
| b | `smoke/workflow_plan_dryrun.json` | Dry-run plan writes **zero** media (asserted: media-file count 3→3, no `output/final.mp4`). |
| c | `smoke/workflow_variants_receipt.json` | `all_variants=True` batch, `receipt_kind: workflow_batch`, `count: 2` (`square`, `wide`), one receipt per variant, no cross-variant leakage. |
| d | `smoke/workflow_resume_receipt.json` | Sabotage→resume: first render keeps intermediates, `output/final.mp4` deleted, `--resume` re-runs only the final step. `resume_used: true`; steps `probe-hero`, `trim-hero`, `resize-hero` carry `skipped: true`; `caption` re-runs. |
| e | `smoke/composite_layer_plan_v2.json` | Composite dry-run with a full-canvas `multiply` blend layer + a `rotation: 15 / pivot: center` layer. `schema_version: 2`, `receipt_kind: layer_plan`, `features.blend_modes: [multiply, normal]`, `features.rotation: true`, `audio_policy: dropped_video_only`, and **`output_path: output/composite.mp4`** (relative — the Part A privacy fix in action). |
| f | `smoke/ssim_stability.json` | Two independent renders of the same spec compared via `engine_compare_quality`: **SSIM = 1.0** (≥ 0.98 threshold). Self-consistency, not a checked-in golden; byte-identity is explicitly not claimed. |

**SSIM value measured: 1.0** (overall quality `high`).

---

## 5. Leak audit

Two independent passes, both **CLEAN**:

1. **Manual sweep** of the packet directory (`docs/proofs/release-1.6.0/`) for absolute home
   prefixes (`/Users`, `/home` followed by a path char), the running username, and
   secret-shaped token prefixes (GitHub PAT / OpenAI `sk-` / AWS `AKIA` / Slack `xox`). Zero
   real hits. (The literal token prefixes are deliberately not reproduced verbatim here so
   this packet never becomes a scanner false-positive; the exact patterns live in
   `tests/test_receipt_privacy.py::_SECRET_PATTERNS`.)
2. **Automated privacy suite** (§1.8, 4 passed) — `tests/test_receipt_privacy.py` scans every
   committed doc/example **including this packet and all `smoke/*.json` receipts**, plus
   freshly produced workflow dry-run/render artifacts and a composite dry-run layer_plan, for
   the same classes of leak. Green.

---

## 6. Residual risks & known deferrals

Everything below is **deferred and fails closed** when requested (documented in plan §9), not
a silent gap:

- **`composite_layers` is NOT a workflow op** this release. It clears its safety bar only
  after nested layer sources become workspace-confined workflow `@refs` hashed into per-step
  `input_hashes` with an escaping-source fail-closed test. Agents still call
  `video_composite_layers` directly.
- **Positioned / scaled / masked / timed blend** — blend ships **full-canvas-only**; any
  other geometry fails closed with `unsupported_blend_geometry`.
- **Rotation combined with a mask** — deferred, fails closed.
- **Per-layer effect routing** (`layer.effects[]`) — deferred, fails closed.
- **Mask-edge / feather semantics** (`layer.mask.edge`) — deferred, fails closed.
- **Audio compositing/mixing** — composite output stays video-only (`-an`); the receipt makes
  this explicit via `audio_policy: dropped_video_only` and `features.audio: dropped` rather
  than dropping audio silently.
- **Parallel / concurrent step execution** — sequential ordered list only.
- **`--force` resume** — a full-job restart only; never a re-run from a mismatched step.
- **Cleanup policy signaling** — the receipt emits `policy: clean-on-success` with
  `cleaned: true` on success and `cleaned: false` to signal retention (on failure or
  `--keep-intermediates`). Plan §5a's `keep-on-failure` string is intentionally **not**
  emitted as a policy value; retention is signaled by `cleaned: false`, not a separate
  policy string.
- **SSIM golden fixtures** — the hardening round added checked-in golden media
  (`tests/fixtures/golden/`) with a fresh-render SSIM comparison (threshold 0.95; same-build
  measures 1.0), plus a normal-vs-multiply blend proof (SSIM ≈ 0.43 < 0.99). The §4f smoke
  evidence remains a same-spec self-consistency check; both now exist and neither claims
  byte-identity.
- **Single-FFmpeg-build test matrix** — a multi-build CI matrix is a documented gap, not
  built. No signed/attested receipts.

### Part A residual (honest)
The privacy fix relativizes the receipt's `output_path`, and `resolved_src`/`mask` were
already relativized via `_receipt_source`. A path the spec **explicitly** places outside the
spec/workspace directory (an absolute source or output the user chose to point elsewhere)
still appears absolute in the receipt — this is the user's own declared location, consistent
across all three fields, and preserved intentionally rather than rewritten. The common
workspace case (relative paths, or files inside the spec dir) is fully relative and
leak-free. No existing test asserts an absolute receipt `output_path`, so scoping was not
forced — the fix is complete for the workspace case without breaking source relativization.

---

## 7. Reproducibility note (plan determinism vs byte determinism)

**Claimed (deterministic and reproducible):** the workflow/spec hash, per-source and per-step
input hashes, the filtergraph summary + its hash, and the recorded output-path structure.
These are stable across runs and machines and are what an inspecting agent should rely on for
provenance and resume integrity. Resume reuse is an **integrity check** on persisted
intermediates (re-hash and compare), never a determinism claim.

**Explicitly NOT claimed:** byte-identical rendered media across FFmpeg builds. Encoder output
can vary between FFmpeg versions/builds. The release asserts **SSIM-threshold stability**
(≥ 0.98; measured 1.0 for two independent renders of the same spec on the same build) and
records the determinism caveat directly in every receipt
(`render_determinism_scope`). Every receipt is honest about this boundary.

---

## 8. Pre-release hardening round (post-review, found-and-fixed before release)

After the eight stories landed, four independent review lanes (code review, security review,
slop audit, verification audit) examined the release. Every finding below was **verified by
the reviewer against code or a live repro** and **fixed before release** with a new regression
test. No finding was deferred except where explicitly justified. Drift counts are unchanged
(**124/103** — no tools or commands added); the 1.6.0 identity tests stay green.

### 8.1 Gates re-run this round (fresh tails)

| Gate | Command | Result |
|---|---|---|
| Full suite | `pytest tests/ -q` | **1867 passed, 15 skipped**, 0 failed (216.98s) |
| Import smoke | `python -c "import mcp_video"` | `import OK, version 1.6.0` |
| Diff hygiene | `git diff --check` | clean |
| Lint | `ruff check .` | All checks passed |
| Build | `python -m build --sdist --wheel` | `mcp_video-1.6.0.tar.gz` (328 KB) + `…-py3-none-any.whl` (406 KB) |
| Metadata | `twine check dist/*` | both PASSED |
| Repo readiness | `scripts/repo-readiness-audit.py` | baseline passed (2 expected pre-commit/pre-push warnings) |
| Privacy suite | `pytest tests/test_receipt_privacy.py -q` | 4 passed |
| Public-site identity | `test_public_site_matches_release_identity` | 1 passed (index.html `1.6.0` / `1,800+` still true — 1867 > 1800) |

Smoke artifacts (§4) were **not** regenerated: no successful-receipt field changed this round
(the only schema addition is the new `workflow_step_failed` error code, which appears on
failure receipts, not the committed success smokes).

### 8.2 Findings → fix → test

| ID | Sev | Finding (verified repro) | Fix | Regression test |
|---|---|---|---|---|
| S1 | HIGH | Artifact writers (`save_plan`/`save_receipt`/`save_receipt_dir`/variant receipts) only rejected null bytes → arbitrary out-of-workspace overwrite. | Shared `_validate_artifact_path` (traversal/symlink/system-dir/dotfile guard; overwrite only existing `.json`). | `test_workflow_security.py` (write_plan/receipt/receipt_dir + variant-dir + success) |
| S2 | HIGH | Params validated by NAME only; string values reached the scaler / `fontsize=` sink (filtergraph file-read primitive). | Value type-check vs engine signature in validator + executor; engine sinks hardened (`resize` `_positive_int`+bound, `add_text` numeric `fontsize`). | `test_workflow_security.py` (6 value repros + 3 engine-sink) |
| S3 | HIGH | No caps on steps/variants/dimensions. | `MAX_WORKFLOW_STEPS=64`, `MAX_WORKFLOW_VARIANTS=32`, resize ≤ `MAX_RESOLUTION`. | `test_workflow_security.py` (step/variant cap + at-cap) |
| C1 | MAJOR | Executor caught `MCPVideoError` only; raw engine exceptions escaped with no receipt. | Catch any `Exception` → wrap `workflow_step_failed`, sanitized, same failed-step/receipt/keep path. | `test_workflow_failclosed.py::test_engine_runtime_error_is_wrapped_and_receipt_written` |
| C2 | MAJOR | `add_text` `font` = spec-controlled path existence oracle. | Excluded from accepted params (`OpAdapter.excluded_params`). | `test_workflow_security.py::test_add_text_font_param_rejected` |
| C3 | MAJOR | `Client.workflow_render(spec=dict)` broken (sources unresolvable, outputs deleted). | Reject dict for render with clear `MCPVideoError`; keep dict for validate/plan. | `test_workflow_failclosed.py::test_client_workflow_render_rejects_dict_spec` |
| C4 | MEDIUM | Two variants overriding the same output path silently overwrote. | Precompute resolved output paths; duplicate → `invalid_workflow_variant`. | `test_workflow_failclosed.py::test_variant_output_collision_fails_closed` |
| C5 | MEDIUM | Raw-relative refs joined without re-confinement (validate→execute symlink TOCTOU). | Re-confine (realpath + relative_to) at execution. | `test_workflow_failclosed.py::test_resolve_ref_path_reconfines_escaping_symlink` |
| C6 | DOCS | Plan §4 illustrative signatures drifted (no `dry_run`; render gained variant/all_variants/save_receipt_dir). | Honest "Signature evolution" note in ADR-0007. | n/a (docs) |
| Q1 | SLOP | Byte-identical `_num`/`_fmt_num` duplicated. | Hoisted to `ffmpeg_helpers._format_ffmpeg_number`. | existing composite/rotate tests |
| Q2 | SLOP | `_RENDER_DETERMINISM_SCOPE` duplicated in planner+executor. | Hoisted to `_versions.RENDER_DETERMINISM_SCOPE`. | existing workflow tests |
| Q3 | SLOP | Client dict-materialization triplicated. | One `_spec_path_from` contextmanager (+ C3). | existing client tests |
| Q4 | SLOP | Dead `OP_ALLOWLIST` (zero consumers). | Deleted from ops + re-export. | import smoke |
| Q5 | SLOP | MCP missing-spec test asserted only `"error" in result`. | Asserts exact code (`invalid_input`) + `suggested_action`. | `test_workflow_server_tool.py` |
| V1 | GAP | No golden SSIM fixtures. | Committed workflow + composite goldens; SSIM ≥ 0.95 (same-build 1.0). | `test_workflow_golden.py` (slow) |
| V2 | GAP | `convert` never exercised end-to-end. | Real mp4→webm workflow render test. | `test_workflow_golden.py::test_convert_op_runs_end_to_end` |
| V3 | GAP | Flagship example unguarded. | Validate `captioned-vertical-short/job.json`. | `test_workflow_golden.py::test_flagship_example_spec_validates` |
| V4 | GAP | No pixel proof blend changes output. | normal vs multiply SSIM ≈ 0.43 (< 0.99). | `test_workflow_golden.py::test_blend_multiply_changes_pixels_vs_normal` |
| F1 | GAP | Download User-Agent hardcoded `mcp-video/1.5.2`. | Derived from `mcp_video.__version__`. | `test_workflow_failclosed.py::test_download_user_agent_uses_package_version` |

### 8.3 Repro confirmation (the reviewers' exact scenarios now fail closed)

- `save_plan="/etc/…json"` / `../escape.json` / `~/.ssh/…json` / overwrite `.txt` → `unsafe_path` / `invalid_output_path` (S1).
- `width="20000"` (resize) → `invalid_workflow_params` (S2).
- `size="24,drawtext=textfile=/etc/hosts"` (add_text) → `invalid_workflow_params` (S2).
- `start=[1,2]` (trim) → `invalid_workflow_params` (S2).

All confirmed via direct `validate_workflow_spec` / writer calls in the new suites.
