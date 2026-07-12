# Plan 00 — Wave 0: Contract Foundation

**Date:** 2026-07-11
**Status:** implementation plan; authorizes no code change by itself. No release actions (see index §3.6).
**Index:** [`2026-07-11-kinocut-ai-video-plan-index.md`](2026-07-11-kinocut-ai-video-plan-index.md)
**Design refs:** editor-design §3, §4.1–4.11, §4.7; coverage items #1, #5–8, #28, #36–45, #47–51, #54–55, #57–60.

> **For implementers:** Work task-by-task in a bounded branch; each step is a checkbox and requires independent review.

**Goal:** Land the shared, strict, versioned record model and private project store that every later wave composes over, plus the additive `ai_video` receipt section, preservation-proof, capability-report, and next-action contracts. No new editing behavior and no public command explosion — this wave is contracts + storage + serialization only.

**Architecture:** Create a new `kinocut/contracts/` package (it does not exist today — confirmed: only `kinocut/client/contracts.py` exists, and that is client method-guard metadata, unrelated) holding Pydantic v2 models with canonical JSON serialization, and a new `kinocut/projectstore/` package for the content-addressed, append-only, lock-guarded project store. Reuse existing primitives: canonical hashing follows the proven `kinocut/semantic/models.py:canonical_digest(value, *, exclude)` pattern (`kinocut/semantic/models.py:23`); receipt privacy sanitizers follow `kinocut/workflow/executor.py:_sanitize_error`/`_strip_workspace`/`_ABSOLUTE_PATH_RE` (executor.py:706–730); errors come only from `kinocut/errors.py` (`MCPVideoError(error_type="validation_error", code=...)`). The receipt extension is additive: legacy workflow receipts are plain dicts built in `kinocut/workflow/executor.py:_render_one` (executor.py:217–243); the `ai_video` section is a new nested key, never a change to existing top-level fields.

**Tech Stack:** Python 3.11+, Pydantic 2.13+ (`ConfigDict(extra="forbid")`, `StrEnum`), `hashlib.sha256`, atomic `os.replace`, `pytest` 8+, Ruff. No FFmpeg and no ML in this wave.

## Global Constraints (subset — see index §3)

- Canonical records are append-only; corrections supersede by `record_id`; history is never rewritten (design §3.2).
- `record_id = sha256` of canonical semantic content, excluding informational fields (`created_at`); `asset_id = sha256:<64 lowercase hex>` of original bytes (design §4.1).
- Unknown fields fail validation when **writing** canonical records; readers may support documented older versions through explicit migrations (design §4).
- Public receipts contain project-relative paths, IDs, and hashes only — never home paths, usernames, raw prompts, credentials, or environment dumps (design §3.2).
- New fields additive; every existing receipt kind keeps a backward-reader fixture (design §4.7, §3.3).
- Errors only from `kinocut/errors.py`; modules ≤ 800 LOC, functions ≤ 80 lines; no dead code (`AGENTS.md`).
- No release actions (index §3.6).

## File Structure

### New production files (PR 0.1)

- `kinocut/contracts/__init__.py` — stable public exports of all record models + `canonical_record_id()`.
- `kinocut/contracts/_common.py` — `RecordBase` (schema_version, record_kind, record_id, project_id, created_at, created_by, supersedes, source_record_ids), `AssetId`/`Sha256` typed aliases, `canonical_record_id(model, *, exclude)`.
- `kinocut/contracts/acceptance.py` — `GenerationAcceptanceSpec` (design §4.2).
- `kinocut/contracts/asset.py` — `AssetRecord`, `GenerationLineage` (design §4.3).
- `kinocut/contracts/verdict.py` — `ClipVerdict` + `Disposition` enum (design §4.4).
- `kinocut/contracts/defect.py` — `DefectFinding`, `DefectCode` taxonomy + `TAXONOMY_VERSION`, `DefectStatus` (design §4.5).
- `kinocut/contracts/protection.py` — `ProtectedElement` + `ElementType`, `DurationPolicy` (design §4.6).
- `kinocut/contracts/review.py` — `ReviewDecision`, `KnownLimitation`, `ApprovalState` (design §4.9).
- `kinocut/contracts/learning.py` — `PromptOutcome`, `UsageEvent`, `CostEvent`, `WorkflowRecipe` (design §4.11).
- `kinocut/contracts/_errors.py` — stable contract error codes (`invalid_record`, `stale_approval_fingerprint`, `unknown_record_field`, `record_supersession_cycle`).
- `kinocut/projectstore/__init__.py` — `open_project`, `append_record`, `read_records`, `ingest_asset`, `rebuild_indexes`.
- `kinocut/projectstore/layout.py` — `.kinocut/` path rules, content-addressed asset path from `asset_id`, sanitized-name policy.
- `kinocut/projectstore/store.py` — atomic append-only JSONL writer with project lock + temp-file replace; supersession resolution; index delete/rebuild.
- `kinocut/projectstore/ingest.py` — byte-hash-first idempotent ingest, re-ingest observation event.
- `kinocut/projectstore/_migrations.py` — versioned reader migrations registry.

### New production files (PR 0.2)

- `kinocut/contracts/receipt_ai_video.py` — `AiVideoReceiptSection` (contract_version, project_id, acceptance_spec_id, ordered_inputs[], transformations[], duration_policy, preservation_proofs[], finding_ids[], review_artifact_ids[], approval_state_id, warnings[]), `OrderedInput`, `Transformation`, `PreservationProof`.
- `kinocut/contracts/capability.py` — `CapabilityReport`, `NextAction` (design §4.10).
- `kinocut/receipts_ai_video.py` — additive helper `attach_ai_video_section(receipt: dict, section: AiVideoReceiptSection) -> dict` that inserts the nested `ai_video` key without touching legacy fields, and `read_ai_video_section(receipt: dict) -> AiVideoReceiptSection | None`.

### Modified production files

- `kinocut/__init__.py` — re-export `kinocut.contracts` as a stable import surface (no behavior change).
- No change to `kinocut/server.py`, CLI, or client in Wave 0 (no public command explosion; surfaces arrive in later waves).

### New tests

- `tests/test_contracts_common.py`, `tests/test_contracts_acceptance.py`, `tests/test_contracts_asset.py`, `tests/test_contracts_verdict.py`, `tests/test_contracts_defect.py`, `tests/test_contracts_protection.py`, `tests/test_contracts_review.py`, `tests/test_contracts_learning.py`
- `tests/test_projectstore_layout.py`, `tests/test_projectstore_store.py`, `tests/test_projectstore_ingest.py`, `tests/test_projectstore_migrations.py`
- `tests/test_receipt_ai_video.py`, `tests/test_contracts_capability.py`
- `tests/test_receipt_backward_readers.py` — every existing receipt kind (`workflow`, `workflow_batch`, `rescue`, `rescue_plan`, `layer_plan`) still parses after the additive section exists.
- `tests/contracts_fixtures.py` — canonical valid/invalid record builders.

### Documentation

- `docs/AI_VIDEO_CONTRACTS.md` — record catalog, ID rules, storage boundary, privacy policy, migration policy. (Additive doc; no CHANGELOG/release entry in Wave 0.)

---

## PR 0.1 — Canonical AI-video records and private project store

Covers foundations for #1–8, #36–45, #48–51, #57–60.

### Task 1: Common record base, typed IDs, and canonical hashing

**Files:** Create `kinocut/contracts/__init__.py`, `kinocut/contracts/_common.py`, `kinocut/contracts/_errors.py`; Test `tests/test_contracts_common.py`, `tests/contracts_fixtures.py`.

**Interfaces:**
- Consumes: `pydantic.BaseModel`/`ConfigDict`/`Field`; `hashlib`; `kinocut.errors.MCPVideoError`; the `canonical_digest` pattern from `kinocut/semantic/models.py:23`.
- Produces: `RecordBase`, `Sha256`, `AssetId`, `canonical_record_id(model, *, exclude=frozenset({"created_at"}))`, `contract_error(message, code)`.

- [ ] **Step 1: Write failing base-model tests**

```python
import pytest
from pydantic import ValidationError
from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts._errors import UNKNOWN_RECORD_FIELD

def test_record_id_excludes_created_at_but_binds_semantics(sample_record_kwargs):
    a = RecordBase(**sample_record_kwargs, created_at="2026-01-01T00:00:00Z")
    b = RecordBase(**sample_record_kwargs, created_at="2027-02-02T00:00:00Z")
    assert canonical_record_id(a) == canonical_record_id(b)  # created_at excluded
    assert canonical_record_id(a).startswith("sha256:")

def test_written_record_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RecordBase.model_validate({"schema_version": 1, "record_kind": "x",
            "project_id": "p", "created_by": "human", "surprise": True})
```

- [ ] **Step 2: Run and confirm RED** — `python3 -m pytest -q tests/test_contracts_common.py` → `ModuleNotFoundError: No module named 'kinocut.contracts'`.

- [ ] **Step 3: Implement `_common.py`** — `RecordBase(BaseModel)` with `model_config = ConfigDict(extra="forbid", frozen=True)` and fields `schema_version: int`, `record_kind: str`, `record_id: Sha256 | None = None`, `project_id: str`, `created_at: str | None = None`, `created_by: str`, `supersedes: Sha256 | None = None`, `source_record_ids: tuple[Sha256, ...] = ()`. `Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]`; `AssetId` identical. `canonical_record_id` computes `"sha256:" + sha256(model_dump(mode="json", exclude=exclude|{"record_id"}), sort_keys, compact separators, utf-8).hexdigest()`. Sanitize `created_by` to `human|agent|tool` + bounded identifier. In `_errors.py` define `INVALID_RECORD`, `UNKNOWN_RECORD_FIELD`, `STALE_APPROVAL_FINGERPRINT`, `RECORD_SUPERSESSION_CYCLE` and `contract_error()` returning `MCPVideoError(error_type="validation_error", code=code, suggested_action={"auto_fix": False})`.

- [ ] **Step 4: Green + lint** — `python3 -m pytest -q tests/test_contracts_common.py && ruff check kinocut/contracts` → all pass.

- [ ] **Step 5: Commit** — `git add kinocut/contracts tests/test_contracts_common.py tests/contracts_fixtures.py && git commit -m "feat(contracts): common record base and canonical ids"`.

### Task 2: Domain record models (acceptance, asset/lineage, verdict, defect, protection, review, learning)

**Files:** Create `kinocut/contracts/{acceptance,asset,verdict,defect,protection,review,learning}.py`; Test the matching `tests/test_contracts_*.py`.

**Interfaces:**
- Produces the models named in File Structure. Enums are `StrEnum` for stable JSON. Each model subclasses `RecordBase` (except embedded value objects) and forbids unknown fields.

- [ ] **Step 1: Write failing model tests** — one per module. Representative assertions:

```python
def test_clip_verdict_dispositions_are_closed():
    from kinocut.contracts.verdict import Disposition
    assert {d.value for d in Disposition} == {
        "approved","approved_with_trim","background_only",
        "repairable","still_frame_salvage","rejected","regenerate"}

def test_approved_with_trim_requires_bounded_range():
    from kinocut.contracts.verdict import ClipVerdict, Disposition
    with pytest.raises(ValidationError):
        ClipVerdict(**_verdict_kwargs(disposition=Disposition.APPROVED_WITH_TRIM, approved_range=None))

def test_defect_status_requires_human_decision_when_not_suspected():
    from kinocut.contracts.defect import DefectFinding, DefectStatus
    with pytest.raises(ValidationError):
        DefectFinding(**_defect_kwargs(status=DefectStatus.CONFIRMED, human_decision_id=None))

def test_protected_element_has_no_force_flag():
    from kinocut.contracts.protection import ProtectedElement
    assert "force" not in ProtectedElement.model_fields
```

- [ ] **Step 2: RED** — `python3 -m pytest -q tests/test_contracts_verdict.py` → import error.

- [ ] **Step 3: Implement models exactly per design §4.2–4.6, §4.9, §4.11.**
  - `Disposition` = the seven values above; `ClipVerdict` binds `asset_hash: AssetId`, optional `approved_range: tuple[float,float] | None`, `acceptance_spec_id`, `reviewer`, `rationale`, `defect_ids`, `review_decision_id`; validator: `approved_with_trim` ⇒ non-empty bounded range; `rejected`/`regenerate` set a flag consulted by later approved-only search.
  - `DefectCode` = the stable initial taxonomy (text drift, identity drift, object mutation, warping, flicker, unwanted camera motion, continuity failure, late-frame degradation, frozen frames, black frames, corrupt frames, broken loop, subtitle overflow, subtitle timing, audio duration, audio style seam, voice identity seam) + `TAXONOMY_VERSION = 1`. `DefectStatus` = `suspected|confirmed|accepted_limitation|resolved|false_positive`; validator: status ≠ `suspected` ⇒ `human_decision_id` required.
  - `ProtectedElement`: `element_type` enum (source asset, audio stream, clip range, timeline range, graphic, subtitle set, timing map, mix, render parameter set), `dependency_fingerprint: Sha256`, `allowed_operations: tuple[str,...]`, `duration_policy`, `human_approval_ref`. No `force` field.
  - `ApprovalState`: `state = pending|approved|invalidated|rejected`, `candidate_artifact`, `dependency_fingerprint`, `required_artifact_ids` + integrity results, `required_human_decisions`, `invalidation_reasons`, `superseding_state_id`. `publishable` is NOT a stored boolean — provide a derived `def is_publishable(...) -> bool` helper only.
  - `GenerationAcceptanceSpec`: store exact text privately — model holds `exact_text_hash` + declared region, not the text, unless an explicit export flag is set.
  - `CostEvent`: unknown cost is explicit (`amount: float | None`, `confidence`), never inferred as zero.

- [ ] **Step 4: Green + lint** — `python3 -m pytest -q tests/test_contracts_acceptance.py tests/test_contracts_asset.py tests/test_contracts_verdict.py tests/test_contracts_defect.py tests/test_contracts_protection.py tests/test_contracts_review.py tests/test_contracts_learning.py && ruff check kinocut/contracts`.

- [ ] **Step 5: Commit** — `git commit -m "feat(contracts): acceptance, asset, verdict, defect, protection, review, learning records"`.

### Task 3: Content-addressed, append-only, lock-guarded project store

**Files:** Create `kinocut/projectstore/{__init__,layout,store,ingest,_migrations}.py`; Test `tests/test_projectstore_{layout,store,ingest,migrations}.py`.

**Interfaces:**
- Consumes: Task 1–2 models; `hashlib`; `os.replace`; a filesystem lock (reuse any existing lock helper if present, else a dot-lock file in `.kinocut/locks/`).
- Produces: `open_project(project_dir)`, `append_record(project, record)`, `read_records(project, record_kind)`, `ingest_asset(project, source_path) -> AssetRecord`, `rebuild_indexes(project)`.

- [ ] **Step 1: Write failing storage tests**

```python
def test_ingest_is_idempotent_by_digest(tmp_path, sample_video):
    proj = open_project(tmp_path / "proj")
    a = ingest_asset(proj, sample_video)
    b = ingest_asset(proj, sample_video)
    assert a.asset_id == b.asset_id
    stored = list((proj.root / ".kinocut" / "assets" / "sha256").glob("*/*"))
    assert len(stored) == 1  # not duplicated

def test_append_is_atomic_and_supersede_only(tmp_path):
    proj = open_project(tmp_path / "proj")
    v1 = append_record(proj, _verdict(record_id=None))
    v2 = append_record(proj, _verdict(supersedes=v1.record_id))
    records = read_records(proj, "clip_verdict")
    assert [r.record_id for r in records] == [v1.record_id, v2.record_id]  # history intact

def test_public_receipt_paths_have_no_home_or_username(tmp_path):
    proj = open_project(tmp_path / "proj")
    rec = ingest_asset(proj, _clip(tmp_path))
    assert str(Path.home()) not in rec.model_dump_json()
```

- [ ] **Step 2: RED** — `python3 -m pytest -q tests/test_projectstore_store.py` → import error.

- [ ] **Step 3: Implement store** — `layout.py` computes the asset path `.kinocut/assets/sha256/<digest>/<sanitized-name>` from `asset_id` and a filename sanitizer (labels only). `ingest.py` hashes source bytes FIRST, returns the existing `AssetRecord` on digest match (recording an optional observation event), and copies bytes into the store before any normalization. `store.py` appends to `.kinocut/records/<kind>.jsonl` under a project lock via temp-file + `os.replace`; a failed write leaves the prior file intact; supersession resolves by walking `supersedes` and rejects cycles (`RECORD_SUPERSESSION_CYCLE`). `rebuild_indexes` deletes and rebuilds `.kinocut/indexes/*` purely from canonical records. All stored paths are project-relative.

- [ ] **Step 4: Green + privacy check** — `python3 -m pytest -q tests/test_projectstore_layout.py tests/test_projectstore_store.py tests/test_projectstore_ingest.py tests/test_receipt_privacy.py`.

- [ ] **Step 5: Commit** — `git commit -m "feat(projectstore): content-addressed append-only project store"`.

### Task 4: Reader migrations and full-suite gate for PR 0.1

**Files:** `kinocut/projectstore/_migrations.py`; `tests/test_projectstore_migrations.py`.

- [ ] **Step 1: Failing migration test** — an older `schema_version` record round-trips through an explicit migration to the current model; an unknown-field write still fails.
- [ ] **Step 2: RED** → **Step 3: Implement** a `MIGRATIONS: dict[(record_kind, from_version), Callable]` registry applied only on read.
- [ ] **Step 4: Full gate** — `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client" && ruff check kinocut/contracts kinocut/projectstore`.
- [ ] **Step 5: Public leak audit**, then commit — `git commit -m "feat(projectstore): explicit reader migrations"`.

---

## PR 0.2 — Receipt and capability contracts

Covers #8, #28, #47, #51, #54–55. Depends on PR 0.1 models.

### Task 5: Additive `ai_video` receipt section and preservation proofs

**Files:** Create `kinocut/contracts/receipt_ai_video.py`, `kinocut/receipts_ai_video.py`; Test `tests/test_receipt_ai_video.py`, `tests/test_receipt_backward_readers.py`.

**Interfaces:**
- Consumes: legacy receipt dicts from `kinocut/workflow/executor.py` (`_render_one` executor.py:217; `_render_all_variants` executor.py:287) and `kinocut/rescue/renderer.py`.
- Produces: `AiVideoReceiptSection`, `OrderedInput`, `Transformation`, `PreservationProof`, `attach_ai_video_section()`, `read_ai_video_section()`.

- [ ] **Step 1: Write failing additive-section tests**

```python
def test_ai_video_section_is_nested_and_additive():
    legacy = {"schema_version": 1, "receipt_kind": "workflow", "steps": [], "outputs": []}
    section = _sample_section()
    merged = attach_ai_video_section(dict(legacy), section)
    assert merged["receipt_kind"] == "workflow"          # unchanged
    assert set(legacy).issubset(merged)                  # nothing removed
    assert merged["ai_video"]["contract_version"] == 1

def test_preservation_proof_states_expected_and_verdict():
    p = PreservationProof(expected="audio stream identical", method="packet_fingerprint",
                          source_fingerprint="sha256:"+"0"*64, output_fingerprint="sha256:"+"0"*64,
                          verdict="preserved")
    assert p.verdict in {"preserved","changed"}
```

- [ ] **Step 2: RED** → **Step 3: Implement** the models per design §4.7: each `OrderedInput` has asset ID, input hash, in/out points, probed duration, role; each `Transformation` has tool/op, sanitized params or param hash, toolchain versions, output duration, output hash, warnings; `PreservationProof` states expected-identical, comparison method, source/output fingerprints, verdict. `attach_ai_video_section` inserts under key `ai_video` only; never mutates legacy top-level keys.

- [ ] **Step 4: Backward-reader fixtures** — `tests/test_receipt_backward_readers.py` loads a golden fixture of every existing receipt kind (`workflow`, `workflow_batch`, `rescue`, `rescue_plan`, `layer_plan`) and asserts `read_ai_video_section(receipt) is None` (absent) without error, and that `kinocut/workflow/inspector.py:inspect_receipt` (inspector.py:60) still parses each.

- [ ] **Step 5: Green + commit** — `python3 -m pytest -q tests/test_receipt_ai_video.py tests/test_receipt_backward_readers.py && git commit -m "feat(receipt): additive ai_video section and preservation proofs"`.

### Task 6: Capability report and next-action contracts

**Files:** Create `kinocut/contracts/capability.py`; Test `tests/test_contracts_capability.py`.

**Interfaces:**
- Produces: `CapabilityReport` (public capability ID, per-surface availability for MCP/Python/CLI, supported formats, required + optional dependencies, availability state, unavailability reason code, remediation text), `NextAction` (action_code, summary, optional sanitized `command_template`, `blocking_record_ids[]`).

- [ ] **Step 1: Failing tests**

```python
def test_capability_report_is_structured_not_help_text():
    r = CapabilityReport(capability_id="inspect.temporal", surfaces={"mcp": True, "python": True, "cli": True},
                         supported_formats=["mp4","mov"], required_deps=["ffmpeg"], optional_deps=[],
                         availability="available", reason_code=None, remediation=None)
    assert r.surfaces["mcp"] is True

def test_next_action_command_template_is_never_auto_executed():
    a = NextAction(action_code="ingest_first", summary="Ingest the source asset before verdict.",
                   command_template="kino assets ingest --source <path>", blocking_record_ids=[])
    assert a.command_template.startswith("kino ")   # advisory string only
```

- [ ] **Step 2: RED** → **Step 3: Implement** per design §4.10. `NextAction` carries at most one suggestion; it is a bounded remediation string, never an autonomy grant (no execution hook).

- [ ] **Step 4: Full-suite gate** — `python3 -m pytest tests/ -x -q --tb=short && python3 -c "import kinocut" && ruff check kinocut/contracts`.

- [ ] **Step 5: Leak audit + commit** — `git commit -m "feat(contracts): capability report and next-action models"`.

---

## Wave 0 completion criteria

- All 0.1 + 0.2 tasks merged; every new module ≤ 800 LOC; each function ≤ 80 lines.
- Full suite green (`python3 -m pytest tests/ -x -q --tb=short`); canonical import assertion passes; Ruff clean.
- Every existing receipt kind still parses (backward-reader fixtures green).
- No public MCP/CLI/Python command added (surfaces are later waves); `docs/AI_VIDEO_CONTRACTS.md` documents the record catalog and storage/privacy boundary.
- Independent code + security review approved; author did not self-approve.
- Release boundary respected: no version bump, tag, publish, submission, deploy, or release (index §3.6).
- Downstream unblocked: Plan 01 (Waves 1–2) and Plan 02 (Wave 3) may begin only after 0.1 and 0.2 merge.
