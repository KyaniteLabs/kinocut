# Dedicated Rescue Pipeline Implementation Plan

> **Historical implementation plan:** Paths and commands below record the MCP
> Video 1.6.0 implementation. The project is now Kinocut; do not use this plan as
> current install or source-layout guidance.

**Status:** Implemented for MCP Video 1.6.0. Current release evidence is recorded in
[`docs/proofs/release-1.6.0/RESCUE_POST_RESCUE_RECEIPT.md`](../../proofs/release-1.6.0/RESCUE_POST_RESCUE_RECEIPT.md).
The unchecked task boxes below preserve the original TDD execution script; the receipt and
commit map are the authoritative completion record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a local-only `plan -> approve -> render -> verify -> package` rescue workflow for one flawed talking-head clip across MCP, CLI, and Python without changing its timeline or silently inventing content.

**Architecture:** Add a focused `mcp_video.rescue` package beside the generic workflow engine. Read-only analyzers emit evidence; the `local_content_preserving` policy is the only component allowed to classify work as executable; the renderer compiles approved repair IDs to a closed operation registry, verifies independently, and atomically promotes a package with a receipt. Existing probe, quality, filter, normalize, convert, transcription, hashing, version, and path-confinement helpers remain the implementation primitives.

**Tech Stack:** Python 3.11+, Pydantic 2.13+, FFmpeg/ffprobe, existing MCP FastMCP decorators, argparse/Rich CLI, pytest 8+, Ruff 0.15+, optional local OpenAI Whisper.

## Global Constraints

- Keep every existing MCP tool, CLI command, Python method, workflow, and receipt compatible; rescue is additive.
- Use policy id `local_content_preserving`, policy version `1`, schema version `1`.
- Never upload media, perform network access, install a dependency, or fall back to a cloud executor.
- Never overwrite the source; keep timeline duration and event order locked; never execute trimming, silence removal, filler removal, retake selection, reordering, synthetic speech, or generated people/objects/events.
- Planning may write only the requested plan and preview artifacts; it must not render or alter the source.
- Rendering accepts repair IDs from the plan only, never raw FFmpeg/filter fragments.
- A successful video rescue requires both a repaired master and H.264/AAC `yuv420p` MP4 sharing copy.
- Captions and transcript are optional derived artifacts: generate them only when local Whisper is available and otherwise record `unavailable` without failing unrelated repairs.
- Stored paths are workspace-relative where possible and must never contain credentials or public home-directory paths.
- Source, plan, policy, executor-version, and intermediate-hash mismatches fail closed.
- Verification failure and cancellation return nonzero CLI status and may not promote a package.
- The intentional 24 fps design-check behavior is out of scope and must remain unchanged.
- Diagnosis has a measured target of about 30 seconds on named benchmark hardware; report honest partial results instead of skipping required safety checks.

---

## File Structure

### New production files

- `mcp_video/rescue/__init__.py`: stable public imports `plan_rescue`, `render_rescue`, and `inspect_rescue`.
- `mcp_video/rescue/models.py`: Pydantic enums and version-1 plan, finding, repair, receipt, verification, and package contracts.
- `mcp_video/rescue/_errors.py`: stable rescue error codes and `rescue_error()`.
- `mcp_video/rescue/capabilities.py`: side-effect-free local capability snapshot used by planning and rendering.
- `mcp_video/rescue/analyzer.py`: source hashing, stream probe, bounded quality measurements, preview timestamps, and candidate findings.
- `mcp_video/rescue/policy.py`: repair-specific thresholds, contraindications, dispositions, and the closed executable catalog.
- `mcp_video/rescue/planner.py`: workspace normalization, policy evaluation, preview generation, canonical plan hashing, and plan serialization.
- `mcp_video/rescue/operations.py`: closed repair-ID-to-engine-call compilation; no arbitrary command/filter input.
- `mcp_video/rescue/verifier.py`: independent source immutability, decode, duration, stream, timestamp, sync, caption, universal-copy, metric-unit, and persisted-hash checks.
- `mcp_video/rescue/renderer.py`: plan revalidation, approvals, isolated job state, bounded execution, cancellation/resume, verification, receipts, and atomic promotion.
- `mcp_video/rescue/inspector.py`: additive, read-only plan/receipt inspection and persisted hash re-checking.
- `mcp_video/server_tools_rescue.py`: three MCP tools.
- `mcp_video/client/rescue.py`: `ClientRescueMixin`.
- `mcp_video/cli/parser/rescue.py`: three CLI parsers.
- `mcp_video/cli/handlers_rescue.py`: CLI dispatch and failure exit semantics.

### Modified production files

- `mcp_video/server.py`: re-export the three registered MCP rescue tools.
- `mcp_video/client/__init__.py`: compose `ClientRescueMixin` into `Client`.
- `mcp_video/cli/parser/__init__.py`: register rescue parsers.
- `mcp_video/__main__.py`: dispatch rescue handlers.
- `mcp_video/cli/formatting.py`: concise plan, receipt, and inspection formatters.
- `mcp_video/doctor.py`: expose a `rescue` capability summary derived from existing checks.

### New tests

- `tests/test_rescue_models.py`
- `tests/test_rescue_capabilities.py`
- `tests/test_rescue_analyzer.py`
- `tests/test_rescue_policy.py`
- `tests/test_rescue_planner.py`
- `tests/test_rescue_operations.py`
- `tests/test_rescue_verifier.py`
- `tests/test_rescue_renderer.py`
- `tests/test_rescue_inspector.py`
- `tests/test_rescue_surfaces.py`
- `tests/test_rescue_e2e.py`
- `tests/rescue_fixtures.py`

### Documentation

- `docs/RESCUE.md`: user contract, trust boundary, examples, artifact schemas, and failure behavior.
- `docs/CLI_REFERENCE.md`, `docs/TOOLS.md`, `docs/PYTHON_CLIENT.md`, `README.md`: public-surface references.
- `skills/mcp-video/SKILL.md`: agent guidance that preserves the explicit approval boundary.
- `CHANGELOG.md`: additive 1.6.x release entry and compatibility notes.

---

### Task 1: Versioned Rescue Contracts And Stable Errors

**Files:**
- Create: `mcp_video/rescue/__init__.py`
- Create: `mcp_video/rescue/models.py`
- Create: `mcp_video/rescue/_errors.py`
- Test: `tests/test_rescue_models.py`

**Interfaces:**
- Consumes: `mcp_video.errors.MCPVideoError`; Pydantic `BaseModel`, `ConfigDict`, and `Field`.
- Produces: `Disposition`, `RepairType`, `Metric`, `Finding`, `Repair`, `PackageIntent`, `RescuePlan`, `VerificationCheck`, `PackageArtifact`, `RescueReceipt`, `canonical_payload()`, `rescue_error()`.

- [ ] **Step 1: Write failing schema and error tests**

```python
from pydantic import ValidationError
import pytest

from mcp_video.rescue._errors import RESCUE_PLAN_MISMATCH, rescue_error
from mcp_video.rescue.models import Disposition, Metric, Repair, RescuePlan


def test_metric_requires_an_explicit_unit():
    with pytest.raises(ValidationError):
        Metric(name="integrated_loudness", value=-27.0, unit="")


def test_plan_rejects_duplicate_repair_ids():
    repair = Repair(
        id="audio_loudness:primary",
        type="audio_loudness",
        disposition=Disposition.SAFE_REPAIR,
        confidence=0.96,
        confidence_rationale="Integrated loudness was measured from the complete audio stream.",
        evidence=[Metric(name="integrated_loudness", value=-27.0, unit="LUFS")],
        parameters={"target_lufs": -16.0, "lra": 11.0},
        expected_benefit="Make speech consistently audible.",
        tradeoffs=["Audio is re-encoded."],
        executor="ffmpeg.loudnorm",
        promotable=True,
    )
    with pytest.raises(ValidationError, match="repair ids must be unique"):
        RescuePlan.model_validate(_minimal_plan([repair, repair]))


def test_rescue_error_exposes_stable_code():
    error = rescue_error("plan changed", RESCUE_PLAN_MISMATCH)
    assert error.code == "rescue_plan_mismatch"
    assert error.suggested_action["auto_fix"] is False
```

The test file must define `_minimal_plan(repairs)` with a relative source path, `sha256:` hashes containing 64 lowercase hex characters, `status="planned"`, policy v1, empty finding buckets, and `plan_sha256=None`; this tests the real model rather than constructing invalid unrelated fields.

- [ ] **Step 2: Run the tests and confirm RED**

Run: `pytest -q tests/test_rescue_models.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'mcp_video.rescue'`.

- [ ] **Step 3: Implement the exact contracts**

Use string enums so JSON remains stable, forbid unknown fields on written v1 models, and allow additive fields only in the inspector reader introduced in Task 7.

```python
class Disposition(StrEnum):
    SAFE_REPAIR = "safe_repair"
    RECOMMENDATION = "recommendation"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class RepairType(StrEnum):
    ROTATION = "rotation"
    CONTAINER_TIMESTAMPS = "container_timestamps"
    METADATA = "metadata"
    UNIVERSAL_MP4 = "universal_mp4"
    AUDIO_LOUDNESS = "audio_loudness"
    AUDIO_DENOISE = "audio_denoise"
    EXPOSURE = "exposure"
    WHITE_BALANCE = "white_balance"
    CAPTIONS_TRANSCRIPT = "captions_transcript"
    STABILIZATION = "stabilization"
    REFRAME = "reframe"
    TIMELINE_EDIT = "timeline_edit"
    SYNTHETIC_CONTENT = "synthetic_content"
    CLOUD_PROCESSING = "cloud_processing"


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    value: float | int | str | bool | None
    unit: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    available: bool = True


class Repair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*:[a-z0-9_-]+$")
    type: RepairType
    disposition: Disposition
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str
    evidence: list[Metric]
    parameters: dict[str, int | float | str | bool]
    expected_benefit: str
    tradeoffs: list[str]
    executor: str | None
    promotable: bool
    reason: str | None = None


class PackageIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["master", "sharing_copy", "captions", "transcript", "receipt"]
    required: bool
    status: Literal["available", "unavailable"]
    reason: str | None = None
```

`RescuePlan` must contain the fields from the approved design plus `workspace_root`, `output_root`, `package_intents`, `capabilities`, `versions`, and `created_at`; `workspace_root` and `output_root` are relative path references, never absolute paths. A model validator must enforce unique repair IDs and exact agreement between each disposition bucket and the repair objects. `RescueReceipt` must contain `receipt_kind="rescue"`, `status` in `completed|failed|cancelled|quarantined`, source/plan/policy hashes, operation entries, verification checks, package artifacts, cleanup/resume state, privacy statement, warnings, and versions. `canonical_payload(model, excluded={"plan_sha256", "created_at", "observed_planning_seconds"})` must use `model_dump(mode="json", exclude=excluded)`, sorted keys, compact separators, and UTF-8 bytes. The exclusions keep the action-bearing plan hash stable while retaining honest wall-clock metadata.

In `_errors.py`, define exactly:

```python
INVALID_RESCUE_INPUT = "invalid_rescue_input"
INVALID_RESCUE_PLAN = "invalid_rescue_plan"
INVALID_RESCUE_RECEIPT = "invalid_rescue_receipt"
RESCUE_SOURCE_MISMATCH = "rescue_source_mismatch"
RESCUE_PLAN_MISMATCH = "rescue_plan_mismatch"
RESCUE_POLICY_VIOLATION = "rescue_policy_violation"
RESCUE_APPROVAL_INVALID = "rescue_approval_invalid"
RESCUE_DEPENDENCY_MISMATCH = "rescue_dependency_mismatch"
RESCUE_INTERMEDIATE_MISMATCH = "rescue_intermediate_mismatch"
RESCUE_CANCELLED = "rescue_cancelled"
RESCUE_VERIFICATION_FAILED = "rescue_verification_failed"
UNSAFE_RESCUE_OUTPUT = "unsafe_rescue_output"
```

`rescue_error(message, code, description=None)` returns `MCPVideoError(error_type="validation_error", code=code, suggested_action={"auto_fix": False, "description": description or _DEFAULT_ACTIONS[code]})`.

- [ ] **Step 4: Run schema tests and lint**

Run: `pytest -q tests/test_rescue_models.py && ruff check mcp_video/rescue tests/test_rescue_models.py`

Expected: all tests pass; Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add mcp_video/rescue tests/test_rescue_models.py
git commit -m "feat: define rescue contracts"
```

### Task 2: Side-Effect-Free Capability Snapshot And Source Analyzer

**Files:**
- Create: `mcp_video/rescue/capabilities.py`
- Create: `mcp_video/rescue/analyzer.py`
- Create: `tests/test_rescue_capabilities.py`
- Create: `tests/test_rescue_analyzer.py`

**Interfaces:**
- Consumes: `probe()`, `_run_ffprobe_json()`, `VisualQualityGuardrails`, workflow `_hash_if_exists()`, `thumbnail()`, `versions()`.
- Produces: `snapshot_capabilities() -> dict[str, Any]`, `analyze_source(source_path: str, workspace_root: Path, preview_dir: Path, *, sample_limit: int = 120) -> AnalysisResult`.

- [ ] **Step 1: Write failing capability tests**

```python
def test_snapshot_never_imports_or_installs_missing_whisper(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    result = snapshot_capabilities(which=lambda name: f"/bin/{name}")
    assert result["local_only"] is True
    assert result["whisper"] == {"available": False, "version": None, "executor": "openai-whisper"}


def test_snapshot_requires_both_ffmpeg_binaries():
    result = snapshot_capabilities(which=lambda name: "/bin/ffmpeg" if name == "ffmpeg" else None)
    assert result["ffmpeg"]["available"] is False
```

- [ ] **Step 2: Run capability tests and confirm RED**

Run: `pytest -q tests/test_rescue_capabilities.py`

Expected: import fails for `mcp_video.rescue.capabilities`.

- [ ] **Step 3: Implement the capability snapshot**

```python
def snapshot_capabilities(
    *,
    which: Callable[[str], str | None] = shutil.which,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
    package_version: Callable[[str], str | None] = _package_version,
) -> dict[str, Any]:
    ffmpeg_path = which("ffmpeg")
    ffprobe_path = which("ffprobe")
    whisper_spec = find_spec("whisper")
    return {
        "local_only": True,
        "ffmpeg": {
            "available": bool(ffmpeg_path and ffprobe_path),
            "ffmpeg": bool(ffmpeg_path),
            "ffprobe": bool(ffprobe_path),
            "version": ffmpeg_version(),
        },
        "whisper": {
            "available": whisper_spec is not None,
            "version": package_version("openai-whisper") if whisper_spec else None,
            "executor": "openai-whisper",
        },
        "filters": {name: _filter_available(name) for name in ("loudnorm", "afftdn", "eq")},
    }
```

Use existing FFmpeg filter discovery, or one bounded `ffmpeg -filters` call cached with `functools.lru_cache`; never import Whisper or load a model during planning.

- [ ] **Step 4: Write failing analyzer tests**

```python
def test_analyzer_is_read_only_and_emits_explicit_units(tmp_path, sample_video):
    source = tmp_path / "input.mp4"
    shutil.copy2(sample_video, source)
    before = _sha256(source)
    result = analyze_source(str(source), tmp_path, tmp_path / "previews")
    assert _sha256(source) == before
    assert result.source.sha256 == f"sha256:{before}"
    assert all(metric.unit and metric.definition for finding in result.findings for metric in finding.evidence)
    assert [p.timestamp_ratio for p in result.previews] == [0.1, 0.5, 0.9]


def test_corrupt_input_fails_before_preview_creation(tmp_path):
    source = tmp_path / "bad.mov"
    source.write_bytes(b"not media")
    with pytest.raises(MCPVideoError) as caught:
        analyze_source(str(source), tmp_path, tmp_path / "previews")
    assert caught.value.code == "invalid_rescue_input"
    assert not (tmp_path / "previews").exists()
```

- [ ] **Step 5: Run analyzer tests and confirm RED**

Run: `pytest -q tests/test_rescue_analyzer.py`

Expected: import fails for `mcp_video.rescue.analyzer`.

- [ ] **Step 6: Implement bounded analysis**

`AnalysisResult` is a frozen dataclass containing `source`, `findings`, `previews`, `estimate`, and `deferred_analyzers`. Normalize `source_path` once with `Path(os.path.realpath(...))`, require it to be a regular file under `workspace_root`, hash it before any preview write, probe streams with ffprobe JSON, and generate three JPGs at 10%, 50%, and 90% only after validation succeeds.

Build candidates with stable IDs and explicit metrics:

```python
def _candidate_findings(info: VideoInfo, raw: dict[str, Any], quality: dict[str, QualityReport]) -> list[Finding]:
    findings: list[Finding] = []
    if info.rotation in {90, 180, 270, -90, -180, -270}:
        findings.append(_rotation_finding(info.rotation))
    if quality["audio_levels"].details.get("has_audio") is not False:
        findings.extend(_audio_findings(quality["audio_levels"]))
    findings.extend(_exposure_findings(quality["brightness"]))
    findings.extend(_white_balance_findings(quality["color_balance"]))
    findings.extend(_stability_findings(raw))
    return findings
```

Run `check_brightness`, `check_audio_levels`, and `check_color_balance`; cap any frame-sampling helper at `sample_limit=120`. Represent analysis failure as `available=False` evidence and a candidate that policy can mark `unavailable`; do not turn missing measurements into zero. Estimate render seconds from a deterministic cost table keyed by pixel count, duration, and proposed executor types; include `platform.processor()`, `platform.system()`, CPU count, `confidence="low|medium"`, and a separate volatile `observed_planning_seconds`. The canonical plan hash excludes only `created_at` and `observed_planning_seconds`, so repeated planning on identical input/configuration/capabilities yields the same `plan_sha256` without hiding action changes.

- [ ] **Step 7: Run focused analyzer tests**

Run: `pytest -q tests/test_rescue_capabilities.py tests/test_rescue_analyzer.py`

Expected: all tests pass, including corrupt input and source immutability.

- [ ] **Step 8: Commit**

```bash
git add mcp_video/rescue/capabilities.py mcp_video/rescue/analyzer.py tests/test_rescue_capabilities.py tests/test_rescue_analyzer.py
git commit -m "feat: analyze rescue inputs locally"
```

### Task 3: Policy Authority, Deterministic Plan, And Preview Artifacts

**Files:**
- Create: `mcp_video/rescue/policy.py`
- Create: `mcp_video/rescue/planner.py`
- Create: `tests/test_rescue_policy.py`
- Create: `tests/test_rescue_planner.py`
- Modify: `mcp_video/rescue/__init__.py`

**Interfaces:**
- Consumes: `AnalysisResult`, `snapshot_capabilities()`, Task 1 models and errors.
- Produces: `evaluate_finding(finding, capabilities) -> Repair`, `plan_rescue(source_path, output_dir, save_plan=None, policy_id="local_content_preserving") -> dict[str, Any]`, `read_plan(path) -> RescuePlan`.

- [ ] **Step 1: Write failing policy matrix tests**

```python
@pytest.mark.parametrize(
    ("repair_type", "confidence", "available", "expected"),
    [
        ("rotation", 1.0, True, "safe_repair"),
        ("audio_loudness", 0.94, True, "safe_repair"),
        ("audio_denoise", 0.89, True, "recommendation"),
        ("timeline_edit", 1.0, True, "blocked"),
        ("synthetic_content", 1.0, True, "blocked"),
        ("cloud_processing", 1.0, True, "blocked"),
    ],
)
def test_policy_dispositions_are_repair_specific(repair_type, confidence, available, expected):
    repair = evaluate_finding(_finding(repair_type, confidence, available), _capabilities(available))
    assert repair.disposition.value == expected


def test_lowering_audio_threshold_cannot_weaken_rotation(monkeypatch):
    monkeypatch.setitem(SAFE_THRESHOLDS, RepairType.AUDIO_LOUDNESS, 0.50)
    repair = evaluate_finding(_finding("rotation", 0.99, True), _capabilities(True))
    assert repair.disposition.value == "recommendation"
```

- [ ] **Step 2: Run policy tests and confirm RED**

Run: `pytest -q tests/test_rescue_policy.py`

Expected: import fails for `mcp_video.rescue.policy`.

- [ ] **Step 3: Implement the closed policy matrix**

```python
POLICY_ID = "local_content_preserving"
POLICY_VERSION = 1
SAFE_THRESHOLDS = {
    RepairType.ROTATION: 1.0,
    RepairType.CONTAINER_TIMESTAMPS: 0.99,
    RepairType.METADATA: 0.99,
    RepairType.AUDIO_LOUDNESS: 0.94,
    RepairType.EXPOSURE: 0.95,
}
BLOCKED_TYPES = {
    RepairType.TIMELINE_EDIT,
    RepairType.SYNTHETIC_CONTENT,
    RepairType.CLOUD_PROCESSING,
}
EXECUTABLE_TYPES = frozenset(SAFE_THRESHOLDS)


def evaluate_finding(finding: Finding, capabilities: Mapping[str, Any]) -> Repair:
    if finding.type in BLOCKED_TYPES:
        return _repair(finding, Disposition.BLOCKED, promotable=False, reason="Blocked by local_content_preserving policy.")
    if not finding.available or not _executor_available(finding.executor, capabilities):
        return _repair(finding, Disposition.UNAVAILABLE, promotable=False, reason="Required local executor is unavailable.")
    threshold = SAFE_THRESHOLDS.get(finding.type)
    if threshold is not None and finding.confidence >= threshold and not finding.contraindications:
        return _repair(finding, Disposition.SAFE_REPAIR, promotable=True)
    return _repair(finding, Disposition.RECOMMENDATION, promotable=finding.timeline_preserving)
```

`AUDIO_DENOISE`, `WHITE_BALANCE`, `STABILIZATION`, and `REFRAME` are recommendation-only in this release. A recommendation may be `promotable=True` only if its type is in a separate `PROMOTABLE_RECOMMENDATIONS` allowlist; initialize that allowlist as empty. This preserves the approval field without claiming an executor contract that has not shipped.

- [ ] **Step 4: Write failing planner tests**

```python
def test_plan_hash_is_deterministic_and_path_private(tmp_path, sample_video):
    source = tmp_path / "incoming" / "clip.mp4"
    source.parent.mkdir()
    shutil.copy2(sample_video, source)
    first = plan_rescue(str(source), str(tmp_path / "out"))
    second = plan_rescue(str(source), str(tmp_path / "out"))
    assert first["plan_sha256"] == second["plan_sha256"]
    assert first["source"]["path"] == "incoming/clip.mp4"
    assert str(Path.home()) not in json.dumps(first)


def test_plan_is_read_only_except_declared_artifacts(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)
    source_hash = _sha256(source)
    plan = plan_rescue(str(source), str(tmp_path / "out"), save_plan=str(tmp_path / "out" / "plan.json"))
    assert _sha256(source) == source_hash
    assert {p.name for p in (tmp_path / "out").iterdir()} == {"plan.json", "previews"}
    assert plan["status"] == "planned"
```

- [ ] **Step 5: Run planner tests and confirm RED**

Run: `pytest -q tests/test_rescue_planner.py`

Expected: import fails for `mcp_video.rescue.planner`.

- [ ] **Step 6: Implement canonical plan construction**

Normalize `source_path`, `output_dir`, and `save_plan` once at entry. Use the common parent of source and output as `workspace_root`; reject either path when realpath confinement fails or any component is a symlink escape. Default `save_plan` to `<output_dir>/rescue-plan.json` only when the caller explicitly passes `save_plan`; otherwise return the plan without writing JSON while still allowing `<output_dir>/previews` because previews are part of the requested diagnosis.

```python
def plan_rescue(
    source_path: str,
    output_dir: str,
    save_plan: str | None = None,
    policy_id: str = POLICY_ID,
) -> dict[str, Any]:
    source, output, workspace = _normalize_entry_paths(source_path, output_dir)
    if policy_id != POLICY_ID:
        raise rescue_error(f"unsupported rescue policy: {policy_id}", RESCUE_POLICY_VIOLATION)
    capabilities = snapshot_capabilities()
    analysis = analyze_source(str(source), workspace, output / "previews")
    repairs = [evaluate_finding(finding, capabilities) for finding in analysis.findings]
    artifact_base = Path(save_plan).resolve().parent if save_plan is not None else output
    plan = RescuePlan.from_analysis(
        analysis,
        repairs,
        capabilities,
        workspace_root=os.path.relpath(workspace, artifact_base),
        output_root=os.path.relpath(output, workspace),
        package_intents=_build_package_intents(analysis.source, capabilities),
    )
    digest = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    plan = plan.model_copy(update={"plan_sha256": digest})
    if save_plan is not None:
        _write_plan(plan, _confine_json(save_plan, workspace))
    return plan.model_dump(mode="json")
```

The common workspace root must not equal the filesystem anchor and must contain both the source and output realpaths. `save_plan`, when provided, must stay inside `output_dir`; store `workspace_root` relative to the plan file's parent (or relative to `output_dir` for an unsaved returned plan) and `output_root` relative to the workspace. `_build_package_intents()` marks master, sharing copy, and receipt required/available; it marks captions/transcript optional/available only when the source has audio and local Whisper exists, otherwise optional/unavailable with a stable reason. `read_plan()` resolves those references from the plan location, rejects traversal/symlink escape, validates with `RescuePlan`, recomputes the canonical hash with the documented volatile-field exclusions, and raises `rescue_plan_mismatch` on any difference.

- [ ] **Step 7: Run policy/planner tests and privacy checks**

Run: `pytest -q tests/test_rescue_policy.py tests/test_rescue_planner.py tests/test_receipt_privacy.py`

Expected: all tests pass; plan JSON contains no absolute home path.

- [ ] **Step 8: Commit**

```bash
git add mcp_video/rescue tests/test_rescue_policy.py tests/test_rescue_planner.py
git commit -m "feat: plan policy-safe video rescues"
```

### Task 4: Closed Repair Operation Registry

**Files:**
- Create: `mcp_video/rescue/operations.py`
- Create: `tests/test_rescue_operations.py`

**Interfaces:**
- Consumes: existing `rotate()`, `normalize_audio()`, `apply_filter()`, `normalize()`, `convert()`, Task 1 `Repair`.
- Produces: `execute_repair(repair: Repair, input_path: str, output_path: str, *, on_progress=None) -> OperationResult`, `make_master()`, `make_universal_copy()`.

- [ ] **Step 1: Write failing registry security tests**

```python
def test_operation_registry_rejects_non_executable_and_unknown_parameters(tmp_path, sample_video):
    repair = _repair("audio_loudness", {"target_lufs": -16.0, "raw_filter": "volume=99"})
    with pytest.raises(MCPVideoError) as caught:
        execute_repair(repair, sample_video, str(tmp_path / "out.mp4"))
    assert caught.value.code == "rescue_policy_violation"


def test_timeline_operation_has_no_registry_entry():
    assert RepairType.TIMELINE_EDIT not in OPERATION_REGISTRY
    assert RepairType.SYNTHETIC_CONTENT not in OPERATION_REGISTRY
    assert RepairType.CLOUD_PROCESSING not in OPERATION_REGISTRY
```

- [ ] **Step 2: Run operation tests and confirm RED**

Run: `pytest -q tests/test_rescue_operations.py`

Expected: import fails for `mcp_video.rescue.operations`.

- [ ] **Step 3: Implement bounded adapters**

```python
@dataclass(frozen=True)
class OperationAdapter:
    allowed_parameters: frozenset[str]
    run: Callable[[str, str, Mapping[str, Any]], None]


OPERATION_REGISTRY = {
    RepairType.ROTATION: OperationAdapter(frozenset({"angle"}), _run_rotation),
    RepairType.CONTAINER_TIMESTAMPS: OperationAdapter(frozenset(), _run_normalize),
    RepairType.METADATA: OperationAdapter(frozenset(), _run_normalize),
    RepairType.AUDIO_LOUDNESS: OperationAdapter(frozenset({"target_lufs", "lra"}), _run_loudness),
    RepairType.EXPOSURE: OperationAdapter(frozenset({"level"}), _run_exposure),
}


def execute_repair(repair: Repair, input_path: str, output_path: str, *, on_progress=None) -> OperationResult:
    if repair.disposition is not Disposition.SAFE_REPAIR:
        raise rescue_error(f"repair {repair.id} is not executable", RESCUE_POLICY_VIOLATION)
    adapter = OPERATION_REGISTRY.get(repair.type)
    if adapter is None or set(repair.parameters) != set(repair.parameters) & adapter.allowed_parameters:
        raise rescue_error(f"repair {repair.id} has no closed adapter or contains unknown parameters", RESCUE_POLICY_VIOLATION)
    started = time.monotonic()
    adapter.run(input_path, output_path, repair.parameters)
    return OperationResult(repair_id=repair.id, output_path=output_path, elapsed_ms=round((time.monotonic() - started) * 1000), sha256=_sha256(output_path))
```

`_run_rotation` calls `rotate(..., angle=normalized_positive_angle, output_path=...)`; `_run_loudness` calls `normalize_audio(..., target_lufs=..., lra=..., output_path=...)`; `_run_exposure` calls `apply_filter(..., "brightness", {"level": level}, output_path=...)` and rejects values outside `[-0.08, 0.08]`; `_run_normalize` calls `normalize(input, output)`.

`make_master(source, approved_outputs, master_path)` copies the source with `shutil.copy2` when no visual/audio repair ran, otherwise copies the final verified intermediate; `make_universal_copy(master, share_path, on_progress)` calls `convert(master, format="mp4", quality="high", output_path=share_path, on_progress=on_progress)`. `UNIVERSAL_MP4` and `CAPTIONS_TRANSCRIPT` are required package intents rather than source-transform repair approvals and must not appear in `OPERATION_REGISTRY` or `safe_repairs`. The sharing copy always runs; captions/transcript run whenever local Whisper is available.

- [ ] **Step 4: Add real-media success tests**

Test rotation dimensions, loudness operation output decodability, bounded exposure, master source-copy behavior, and universal copy codec/pixel format. Mark only tests over 10 seconds with `@pytest.mark.slow`.

- [ ] **Step 5: Run focused operation suite**

Run: `pytest -q tests/test_rescue_operations.py`

Expected: all success and rejection tests pass.

- [ ] **Step 6: Commit**

```bash
git add mcp_video/rescue/operations.py tests/test_rescue_operations.py
git commit -m "feat: execute closed rescue operations"
```

### Task 5: Independent Verification, Package Manifest, And Inspection

**Files:**
- Create: `mcp_video/rescue/verifier.py`
- Create: `mcp_video/rescue/inspector.py`
- Create: `tests/test_rescue_verifier.py`
- Create: `tests/test_rescue_inspector.py`

**Interfaces:**
- Consumes: ffprobe JSON, source/plan/receipt models, hash helpers.
- Produces: `verify_package(source, master, sharing_copy, caption_path=None, transcript_path=None) -> list[VerificationCheck]`, `inspect_rescue(path) -> dict[str, Any]`.

- [ ] **Step 1: Write failing verifier tests**

```python
def test_verifier_rejects_duration_regression(tmp_path, sample_video):
    shortened = _trim_to_one_second(sample_video, tmp_path / "short.mp4")
    checks = verify_package(sample_video, shortened, shortened)
    duration = next(check for check in checks if check.id == "timeline_duration")
    assert duration.passed is False
    assert duration.metric.unit == "seconds"


def test_universal_copy_contract_is_explicit(tmp_path, sample_video):
    checks = verify_package(sample_video, sample_video, sample_video)
    universal = next(check for check in checks if check.id == "universal_mp4_contract")
    assert universal.metric.definition
    assert universal.details["required"] == {"container": "mp4", "video_codec": "h264", "pixel_format": "yuv420p", "audio_codec": "aac_or_absent"}
```

- [ ] **Step 2: Run verifier tests and confirm RED**

Run: `pytest -q tests/test_rescue_verifier.py`

Expected: import fails for `mcp_video.rescue.verifier`.

- [ ] **Step 3: Implement all independent checks**

`verify_package()` must always return checks with these exact IDs:

```python
CHECK_IDS = (
    "source_unchanged",
    "master_full_decode",
    "sharing_full_decode",
    "timeline_duration",
    "monotonic_timestamps",
    "source_stream_coverage",
    "audio_video_sync",
    "caption_sync",
    "spoken_content_coverage",
    "universal_mp4_contract",
    "metric_units",
    "persisted_hashes",
)
```

Full decode uses `ffmpeg -v error -i <path> -map 0 -f null -` with the existing bounded command runner. Duration tolerance is `max(0.10, 2 / source_fps)` seconds. Timestamp monotonicity inspects bounded packet PTS/DTS from each output stream. Stream coverage compares source stream types and counts, allowing only an explicitly declared derived subtitle artifact. A/V sync compares the last video and audio packet end times within `max(0.10, 2/source_fps)`. Caption sync requires every segment to satisfy `0 <= start < end <= master_duration + tolerance`. Spoken-content coverage is `not_applicable` when no local transcript exists; when it exists, non-empty caption segment text and transcript text must agree after whitespace normalization. Universal copy requires MP4, H.264, `yuv420p`, and AAC when audio exists. Every numeric result must be wrapped in `Metric` with unit and definition.

- [ ] **Step 4: Write failing additive inspection tests**

```python
def test_inspector_tolerates_future_additive_fields(tmp_path):
    receipt = _valid_receipt()
    receipt["future_field"] = {"kept": True}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    inspected = inspect_rescue(str(path))
    assert inspected["kind"] == "rescue"
    assert inspected["integrity"]["all_present"] is True


def test_inspector_never_modifies_media(tmp_path, sample_video):
    receipt_path = _receipt_for(tmp_path, sample_video)
    before = _sha256(sample_video)
    inspect_rescue(str(receipt_path))
    assert _sha256(sample_video) == before
```

- [ ] **Step 5: Implement read-only inspection**

Read JSON as a plain mapping, accept only `receipt_kind in {"rescue_plan", "rescue"}`, require known v1 fields, ignore additional fields, and re-hash every recorded source/output artifact relative to the receipt directory. Return `kind`, `schema_version`, `tool`, `status`, disposition counts, approved/applied/skipped repair IDs, verification summary, package manifest, privacy, warnings, cleanup/resume state, and `integrity={all_present, all_matching, artifacts}`. Never call a render engine.

- [ ] **Step 6: Run verifier/inspector suites**

Run: `pytest -q tests/test_rescue_verifier.py tests/test_rescue_inspector.py tests/test_receipt_privacy.py`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add mcp_video/rescue/verifier.py mcp_video/rescue/inspector.py tests/test_rescue_verifier.py tests/test_rescue_inspector.py
git commit -m "feat: verify and inspect rescue packages"
```

### Task 6: Renderer, Atomic Promotion, Cancellation, And Resume

**Files:**
- Create: `mcp_video/rescue/renderer.py`
- Create: `tests/test_rescue_renderer.py`
- Modify: `mcp_video/rescue/__init__.py`

**Interfaces:**
- Consumes: `read_plan()`, closed operations, verifier, receipt contracts.
- Produces: `render_rescue(plan_path, approved_repair_ids=None, save_receipt=None, resume_receipt=None, cancel_file=None, keep_intermediates=False) -> dict[str, Any]`.

- [ ] **Step 1: Write failing approval and staleness tests**

```python
def test_renderer_executes_only_approved_safe_repairs(tmp_path, sample_video):
    plan_path, plan = _planned_fixture(tmp_path, sample_video)
    safe = [r["id"] for r in plan["safe_repairs"]]
    receipt = render_rescue(str(plan_path), approved_repair_ids=safe[:1])
    assert receipt["approved_repair_ids"] == safe[:1]
    assert set(receipt["applied_repair_ids"]) <= set(safe[:1])


def test_renderer_fails_closed_when_source_changes(tmp_path, sample_video):
    source = tmp_path / "mutable.mp4"
    shutil.copy2(sample_video, source)
    plan_path, plan = _planned_fixture(tmp_path, str(source))
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path))
    assert caught.value.code == "rescue_source_mismatch"


def test_renderer_rejects_recommendation_approval(tmp_path, sample_video):
    plan_path, plan = _planned_fixture(tmp_path, sample_video, recommendation="stabilization:crop")
    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), approved_repair_ids=["stabilization:crop"])
    assert caught.value.code == "rescue_approval_invalid"
```

- [ ] **Step 2: Run renderer tests and confirm RED**

Run: `pytest -q tests/test_rescue_renderer.py -k 'approval or source_changes'`

Expected: import fails for `mcp_video.rescue.renderer`.

- [ ] **Step 3: Implement preflight and isolated state**

`approved_repair_ids=None` means all transformation IDs in `safe_repairs`, preserving the explicit plan/render boundary while giving each render a recorded approval set. Any supplied ID outside the plan's safe bucket fails. Required non-transforming package intents (`master`, `sharing_copy`, optional local captions/transcript, and receipt) execute independently of the approval list because they are the already-declared output contract, not edits to source content. Recompute source and plan hashes, compare policy id/version and capability executor versions, and create `<output_root>/.rescue-work/<plan-hash-prefix>-<run-id>/` with `state.json`, `intermediates/`, and `package/`.

```python
def render_rescue(
    plan_path: str,
    approved_repair_ids: Sequence[str] | None = None,
    save_receipt: str | None = None,
    resume_receipt: str | None = None,
    cancel_file: str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    plan = read_plan(plan_path)
    context = _preflight(plan_path, plan, approved_repair_ids, resume_receipt)
    try:
        return _run_and_promote(context, save_receipt, cancel_file, keep_intermediates)
    except RescueCancellation as exc:
        receipt = _finish_non_success(context, "cancelled", exc)
        _write_requested_receipt(receipt, save_receipt)
        raise rescue_error("rescue cancelled; no package was promoted", RESCUE_CANCELLED) from exc
```

- [ ] **Step 4: Implement stage execution and atomic promotion**

Stages are exactly `repair:<id>` in plan order, `master`, `sharing_copy`, optional `captions_transcript`, and `verification`. Check `cancel_file` before and after every stage and in `convert(..., on_progress=...)`. Write `state.json` atomically after each completed stage with input hash, output hash, executor version, elapsed time, and status. Use `os.replace(job_package_dir, final_package_dir)` only after every gating verification check passes. The final directory is `<output_root>/<sanitized-source-stem>-rescue-<plan-hash-prefix>`; reject an existing final directory instead of overwriting it. Write the receipt into the package before promotion and, when requested, write a second confined receipt copy after promotion.

- [ ] **Step 5: Write failing cancellation and quarantine tests**

```python
def test_cancel_marker_prevents_promotion_and_records_receipt(tmp_path, sample_video):
    plan_path, _ = _planned_fixture(tmp_path, sample_video)
    cancel = tmp_path / "cancel"
    cancel.write_text("stop", encoding="utf-8")
    receipt = tmp_path / "cancelled.json"
    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt), cancel_file=str(cancel))
    assert caught.value.code == "rescue_cancelled"
    assert json.loads(receipt.read_text())["status"] == "cancelled"
    assert not list(tmp_path.glob("*-rescue-*"))


def test_verification_failure_quarantines_without_success_status(tmp_path, sample_video, monkeypatch):
    plan_path, _ = _planned_fixture(tmp_path, sample_video)
    monkeypatch.setattr("mcp_video.rescue.renderer.verify_package", lambda *a, **k: [_failed_check()])
    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(tmp_path / "failed.json"))
    assert caught.value.code == "rescue_verification_failed"
    receipt = json.loads((tmp_path / "failed.json").read_text())
    assert receipt["status"] == "quarantined"
    assert receipt["package"]["promoted"] is False
```

- [ ] **Step 6: Implement cancellation cleanup and failed verification behavior**

Cooperative cancellation may wait for the current bounded engine call to finish, but it must detect the marker before promotion, leave no child process, remove incomplete output files, and retain only hash-verified completed intermediates needed for resume. Verification failure moves the job directory to `<output_root>/.rescue-quarantine/<run-id>` and records that relative path; it may never return `status="completed"`.

- [ ] **Step 7: Write failing resume-integrity tests**

```python
def test_resume_reuses_only_matching_completed_stages(tmp_path, sample_video, monkeypatch):
    cancelled_receipt = _cancel_after_first_stage(tmp_path, sample_video)
    calls = _spy_operations(monkeypatch)
    receipt = render_rescue(cancelled_receipt.plan_path, resume_receipt=cancelled_receipt.receipt_path)
    assert cancelled_receipt.completed_repair_id not in calls.repair_ids
    assert receipt["resume"]["used"] is True


def test_resume_rejects_tampered_intermediate(tmp_path, sample_video):
    cancelled_receipt = _cancel_after_first_stage(tmp_path, sample_video)
    Path(cancelled_receipt.intermediate_path).write_bytes(b"tampered")
    with pytest.raises(MCPVideoError) as caught:
        render_rescue(cancelled_receipt.plan_path, resume_receipt=cancelled_receipt.receipt_path)
    assert caught.value.code == "rescue_intermediate_mismatch"
```

- [ ] **Step 8: Implement resume gates**

Resume requires matching source hash, plan hash, policy id/version, MCP Video version, FFmpeg version, approved ID set, and every completed intermediate hash. It reuses the prior job directory only after realpath confinement under `.rescue-work`; otherwise raise `rescue_intermediate_mismatch`. Reuse completed stages in order until the first absent or nonmatching stage, then rerun that stage and all later stages.

- [ ] **Step 9: Run the complete renderer slice**

Run: `pytest -q tests/test_rescue_models.py tests/test_rescue_policy.py tests/test_rescue_operations.py tests/test_rescue_verifier.py tests/test_rescue_renderer.py`

Expected: all success, failure, cancellation, quarantine, and resume tests pass.

- [ ] **Step 10: Commit**

```bash
git add mcp_video/rescue/renderer.py mcp_video/rescue/__init__.py tests/test_rescue_renderer.py
git commit -m "feat: render and resume verified rescues"
```

### Task 7: MCP, CLI, Python, Formatting, And Exit Parity

**Files:**
- Create: `mcp_video/server_tools_rescue.py`
- Create: `mcp_video/client/rescue.py`
- Create: `mcp_video/cli/parser/rescue.py`
- Create: `mcp_video/cli/handlers_rescue.py`
- Create: `tests/test_rescue_surfaces.py`
- Modify: `mcp_video/server.py`
- Modify: `mcp_video/client/__init__.py`
- Modify: `mcp_video/cli/parser/__init__.py`
- Modify: `mcp_video/__main__.py`
- Modify: `mcp_video/cli/formatting.py`

**Interfaces:**
- Consumes: Task 3, 5, and 6 public rescue functions.
- Produces: `video_rescue_plan`, `video_rescue_render`, `video_rescue_inspect`; CLI commands `rescue-plan`, `rescue-render`, `rescue-inspect`; `ClientRescueMixin`.

- [ ] **Step 1: Write failing parser and Python-client parity tests**

```python
def test_rescue_render_parser_preserves_explicit_approval_boundary():
    args = build_parser().parse_args(["rescue-render", "--plan", "plan.json", "--approve", "rotation:metadata", "--approve", "audio_loudness:primary"])
    assert args.plan == "plan.json"
    assert args.approve == ["rotation:metadata", "audio_loudness:primary"]


def test_python_client_delegates_exact_contract(monkeypatch):
    monkeypatch.setattr("mcp_video.rescue.render_rescue", lambda *a, **k: {"args": a, "kwargs": k})
    result = Client().rescue_render("plan.json", approved_repair_ids=["rotation:metadata"], cancel_file="cancel")
    assert result["args"] == ("plan.json",)
    assert result["kwargs"]["approved_repair_ids"] == ["rotation:metadata"]
```

- [ ] **Step 2: Run surface tests and confirm RED**

Run: `pytest -q tests/test_rescue_surfaces.py -k 'parser or client'`

Expected: parser rejects `rescue-render` and `Client` has no `rescue_render` method.

- [ ] **Step 3: Add parsers and client mixin**

```python
class ClientRescueMixin:
    def rescue_plan(self, source: str, output_dir: str, save_plan: str | None = None, policy: str = "local_content_preserving") -> dict[str, Any]:
        from ..rescue import plan_rescue
        return plan_rescue(source, output_dir, save_plan, policy)

    def rescue_render(self, plan: str, approved_repair_ids: Sequence[str] | None = None, save_receipt: str | None = None, resume_receipt: str | None = None, cancel_file: str | None = None, keep_intermediates: bool = False) -> dict[str, Any]:
        from ..rescue import render_rescue
        return render_rescue(plan, approved_repair_ids, save_receipt, resume_receipt, cancel_file, keep_intermediates)

    def rescue_inspect(self, receipt: str) -> dict[str, Any]:
        from ..rescue import inspect_rescue
        return inspect_rescue(receipt)
```

CLI arguments:
- `rescue-plan --source PATH --output-dir DIR [--save-plan JSON] [--policy local_content_preserving]`
- `rescue-render --plan JSON [--approve ID ...] [--save-receipt JSON] [--resume RECEIPT] [--cancel-file PATH] [--keep-intermediates]`
- `rescue-inspect --receipt JSON`

Register parser and handler modules in the same positions as workflow. Do not add a `rescue` one-command wrapper.

- [ ] **Step 4: Write failing MCP and CLI exit tests**

```python
def test_mcp_plan_returns_standard_result(monkeypatch):
    monkeypatch.setattr("mcp_video.server_tools_rescue.plan_rescue", lambda *a, **k: {"status": "planned"})
    result = video_rescue_plan("clip.mp4", "out")
    assert result["success"] is True
    assert result["data"]["status"] == "planned"


def test_cli_verification_failure_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_video.rescue.render_rescue", _raise_verification_failure)
    result = _run_cli(["--format", "json", "rescue-render", "--plan", "plan.json"])
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]["code"] == "rescue_verification_failed"
```

- [ ] **Step 5: Add MCP tools, handlers, and formatters**

MCP functions use `@mcp.tool()`, `@_safe_tool`, and `_result()` exactly like workflow tools. Keep signatures aligned with the client methods. Text plan output must show source, disposition counts, safe repair IDs, unavailable capabilities, preview paths, and estimate. Render output must show status, package path, applied/skipped IDs, verification pass count, and receipt. Inspect output must show status, integrity, verification failures, privacy, and resume/cleanup state. JSON output returns the underlying dict unchanged.

- [ ] **Step 6: Run all surface tests and existing registration tests**

Run: `pytest -q tests/test_rescue_surfaces.py tests/test_server.py tests/test_client.py tests/test_cli_parsers.py tests/test_cli_handlers.py`

Expected: all tests pass; existing commands retain their signatures.

- [ ] **Step 7: Commit**

```bash
git add mcp_video/server.py mcp_video/server_tools_rescue.py mcp_video/client mcp_video/cli mcp_video/__main__.py tests/test_rescue_surfaces.py
git commit -m "feat: expose rescue across mcp cli and python"
```

### Task 8: Optional Local Captions And Doctor Rescue Summary

**Files:**
- Modify: `mcp_video/rescue/capabilities.py`
- Modify: `mcp_video/rescue/renderer.py`
- Modify: `mcp_video/doctor.py`
- Modify: `tests/test_rescue_capabilities.py`
- Modify: `tests/test_rescue_renderer.py`
- Modify: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `ai_transcribe(video, output_srt, model="base", language=None)` and its returned transcript/segments/language.
- Produces: optional `captions.srt`, `transcript.txt`, manifest availability reason, and `doctor()["rescue"]`.

- [ ] **Step 1: Write failing missing/local model tests**

```python
def test_missing_whisper_records_unavailable_without_import_or_network(tmp_path, sample_video, monkeypatch):
    monkeypatch.setattr("mcp_video.rescue.capabilities.importlib.util.find_spec", lambda name: None)
    plan_path, plan = _planned_fixture(tmp_path, sample_video)
    receipt = render_rescue(str(plan_path))
    artifacts = {a["kind"]: a for a in receipt["package"]["artifacts"]}
    assert artifacts["captions"]["status"] == "unavailable"
    assert artifacts["transcript"]["status"] == "unavailable"
    assert receipt["status"] == "completed"


def test_local_whisper_writes_sidecars_without_burning_them(tmp_path, sample_video, monkeypatch):
    monkeypatch.setattr("mcp_video.rescue.renderer.ai_transcribe", _fake_local_transcript)
    plan_path, _ = _planned_fixture(tmp_path, sample_video, whisper_available=True)
    receipt = render_rescue(str(plan_path))
    artifacts = {a["kind"]: a for a in receipt["package"]["artifacts"]}
    assert artifacts["captions"]["path"].endswith("captions.srt")
    assert artifacts["transcript"]["path"].endswith("transcript.txt")
    assert _subtitle_stream_count(artifacts["master"]["path"]) == 0
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_rescue_renderer.py -k 'whisper or sidecar'`

Expected: artifact manifest does not yet contain the required caption/transcript status.

- [ ] **Step 3: Implement local-only sidecar generation**

At plan time, record the `captions` and `transcript` package intents as `available` only when an audio stream and local Whisper exist; otherwise record them as `unavailable` with reason `missing_local_whisper` or `no_audio_stream`. Do not put package intents in `safe_repairs`. At render time, call `ai_transcribe(master, output_srt=<job>/package/captions.srt, model="base")`, write `transcript.txt` from returned `transcript`, record Whisper package/model versions, and run caption verification. Catch only `missing_whisper` as `unavailable`; transcription execution errors quarantine the package because a capability declared available at plan time failed. Never call subtitle-burn engines.

- [ ] **Step 4: Write failing doctor summary test**

```python
def test_doctor_reports_rescue_readiness_from_existing_checks(monkeypatch):
    report = run_diagnostics(which=_which_ffmpeg_only, find_spec=lambda name: None, package_version=lambda name: None)
    assert report["rescue"] == {
        "core_ready": True,
        "local_only": True,
        "captions_available": False,
        "automatic_repair_types": ["audio_loudness", "container_timestamps", "exposure", "metadata", "rotation", "universal_mp4"],
    }
```

- [ ] **Step 5: Add doctor summary without duplicate probes**

Build the summary from the already-computed `checks` list; do not rerun commands or import optional packages. Include captions in `automatic_repair_types` only when Whisper is available.

- [ ] **Step 6: Run capability/doctor/renderer tests**

Run: `pytest -q tests/test_rescue_capabilities.py tests/test_rescue_renderer.py tests/test_doctor.py`

Expected: all tests pass with and without mocked Whisper.

- [ ] **Step 7: Commit**

```bash
git add mcp_video/rescue mcp_video/doctor.py tests/test_rescue_capabilities.py tests/test_rescue_renderer.py tests/test_doctor.py
git commit -m "feat: add local rescue sidecars and readiness"
```

### Task 9: Reproducible Fixture Matrix, End-To-End Gates, And Performance Receipt

**Files:**
- Create: `tests/rescue_fixtures.py`
- Create: `tests/test_rescue_e2e.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: public `plan_rescue`, `render_rescue`, `inspect_rescue` only.
- Produces: reproducible FFmpeg fixtures and release-level acceptance evidence.

- [ ] **Step 1: Add deterministic fixture builders**

Implement `make_rescue_fixture(tmp_path, *, rotation=0, brightness=0.0, volume_db=0.0, noise=False, vfr=False, drift_ms=0, container="mp4", hostile_name=False) -> Path`. Build inputs exclusively from FFmpeg lavfi sources with fixed duration `3.0`, resolution `320x240`, rate `30`, H.264/AAC defaults, and `-threads 1`; use metadata rotation, `eq`, `volume`, `anoisesrc`, `setpts`, and `adelay` only for the requested defect. Add `make_corrupt_fixture`, `make_long_unicode_fixture`, and `make_unsupported_codec_fixture` with fixed bytes/parameters.

- [ ] **Step 2: Write the flagship E2E test**

```python
@pytest.mark.slow
def test_fix_this_clip_end_to_end(tmp_path):
    source = make_rescue_fixture(tmp_path, rotation=90, brightness=-0.18, volume_db=-18, noise=True)
    source_hash = _sha256(source)
    plan_path = tmp_path / "diagnosis" / "plan.json"
    plan = plan_rescue(str(source), str(tmp_path / "diagnosis"), str(plan_path))
    receipt = render_rescue(str(plan_path))
    inspection = inspect_rescue(receipt["receipt_path"])
    assert _sha256(source) == source_hash
    assert plan["status"] == "planned"
    assert receipt["status"] == "completed"
    assert {"master", "sharing_copy"} <= {a["kind"] for a in receipt["package"]["artifacts"] if a["status"] == "available"}
    assert inspection["integrity"]["all_matching"] is True
    assert all(check["passed"] for check in receipt["verification"] if check["gating"])
```

- [ ] **Step 3: Run flagship test and fix only fixture-contract mismatches**

Run: `pytest -q tests/test_rescue_e2e.py::test_fix_this_clip_end_to_end`

Expected: PASS. Any production defect discovered here starts a fresh failing unit test in the owning task's test file before changing production code.

- [ ] **Step 4: Add hostile success/failure matrix**

Parameterize tests for portrait rotation, dim footage, quiet speech, clipping, hum/noise recommendation, malformed timestamps, VFR, A/V drift, MOV/WebM input, missing Whisper, interrupted/resumed render, metric tradeoff, Unicode/long/hostile names, symlink escape, corrupt media, and unsupported codec. Assert stable error codes, no source mutation, no cloud/network mock calls, no promoted package on failure, and bounded cleanup. Keep shaky/stabilization, wind/echo denoise, crop/reframe, deblur/upscale, HDR, background work, and timeline edits recommendation-only or blocked.

- [ ] **Step 5: Add deterministic and FFmpeg compatibility checks**

Generate the same plan twice and assert identical `plan_sha256`; render twice to distinct roots and compare stream topology, duration tolerance, metric units, applied operation parameters, and artifact presence rather than byte hashes. Parameterize available CI FFmpeg versions through the existing matrix job; do not weaken checks for older supported builds.

- [ ] **Step 6: Add measured diagnosis performance report**

For a 60-second 1080p synthetic talking-head-equivalent fixture, record cold and warm planning wall time, CPU, memory, OS, FFmpeg version, clip properties, enabled analyzers, sample limit, local model availability, predicted seconds, actual seconds, and absolute estimate error into pytest's captured JSON artifact. Assert only that required fields exist and planning remains bounded by `sample_limit`; document the approximately 30-second target without making heterogeneous CI hardware fail on elapsed time.

- [ ] **Step 7: Run focused and full relevant suites**

Run: `pytest -q tests/test_rescue_*.py`

Expected: all rescue tests pass.

Run: `pytest -q tests/test_workflow_*.py tests/test_server.py tests/test_client.py tests/test_cli_parsers.py tests/test_cli_handlers.py tests/test_doctor.py tests/test_receipt_privacy.py`

Expected: all relevant existing suites pass with no compatibility regressions.

- [ ] **Step 8: Run adversarial and static gates**

Run: `pytest -q tests/test_red_team.py tests/test_security.py tests/test_path_security.py && ruff check mcp_video tests`

Expected: all tests pass; Ruff reports `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
git add tests/conftest.py tests/rescue_fixtures.py tests/test_rescue_e2e.py
git commit -m "test: prove rescue pipeline end to end"
```

### Task 10: Documentation, Agent Skill, Changelog, And Release Receipt

**Files:**
- Create: `docs/RESCUE.md`
- Modify: `README.md`
- Modify: `docs/CLI_REFERENCE.md`
- Modify: `docs/TOOLS.md`
- Modify: `docs/PYTHON_CLIENT.md`
- Modify: `skills/mcp-video/SKILL.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: final public signatures and verified artifact examples.
- Produces: copy-pasteable user/agent guidance and release verification receipt.

- [ ] **Step 1: Write documentation contract tests**

Add assertions to `tests/test_rescue_surfaces.py` that `docs/RESCUE.md` contains all three MCP, CLI, and Python names; explicitly says local-only, source immutable, timeline locked, captions not burned, missing Whisper nonfatal, plan approval required, and no one-command `rescue`; and that the skill instructs agents to inspect the plan before render.

- [ ] **Step 2: Run documentation tests and confirm RED**

Run: `pytest -q tests/test_rescue_surfaces.py -k documentation`

Expected: FAIL because `docs/RESCUE.md` does not exist.

- [ ] **Step 3: Write public documentation with exact examples**

Document these commands without local absolute paths:

```bash
mcp-video rescue-plan --source media/clip.mov --output-dir rescue-output --save-plan rescue-output/plan.json
mcp-video --format json rescue-inspect --receipt rescue-output/plan.json
mcp-video rescue-render --plan rescue-output/plan.json --approve rotation:metadata --approve audio_loudness:primary --save-receipt rescue-output/render-receipt.json
mcp-video rescue-inspect --receipt rescue-output/render-receipt.json
```

Include Python and MCP equivalents, disposition definitions, repair catalog, package manifest, cancellation marker behavior, resume gates, stable errors, compatibility caveats, optional Whisper installation as a manual choice, and the measured-performance reporting contract. State that omitting `--approve` approves all policy-classified `safe_repair` IDs from the already reviewed plan, never recommendations.

- [ ] **Step 4: Update the MCP Video skill**

Teach agents this exact sequence: call plan, present safe/recommended/unavailable/blocked work and previews, obtain or infer explicit user approval only for safe IDs, call render with IDs, inspect receipt, and report package plus verification. Prohibit calling render directly from an unreviewed plan, adding recommendation IDs, using cloud tools, burning captions, or treating `unavailable` as failure.

- [ ] **Step 5: Update changelog and compatibility statement**

Add a 1.6.x `Added` entry for the three surfaces and rescue package; a `Safety` entry for local-only, timeline lock, staleness, quarantine, and receipts; and a `Compatibility` entry stating existing APIs are unchanged, Whisper remains optional, the sharing copy is additive, and intentional 24 fps behavior is unchanged.

- [ ] **Step 6: Run public leak audit and complete test suite**

Run: `rg -n "$(printf '/%s/' Users)[[:alnum:]_.-]+/|\.codex|\.claude|API[_-]?KEY|Bearer " README.md skills CHANGELOG.md mcp_video tests && rg -n --glob '!superpowers/**' "$(printf '/%s/' Users)[[:alnum:]_.-]+/|\.codex|\.claude|API[_-]?KEY|Bearer " docs`

Expected: no newly added public-path, username, credential, or process leakage.

Run: `pytest -q`

Expected: complete suite passes.

Run: `ruff check mcp_video tests && python -m build`

Expected: Ruff passes; wheel and sdist build successfully; rescue modules are present in the wheel and repository-only tests are absent.

- [ ] **Step 7: Run final manual CLI smoke**

Use a generated 3-second fixture, then run `rescue-plan`, JSON `rescue-inspect`, `rescue-render`, and final `rescue-inspect`. Confirm source hash unchanged, package has master/share/receipt, captions are available or explicitly unavailable, all gating verification checks pass, and text/JSON output agree.

- [ ] **Step 8: Commit**

```bash
git add README.md CHANGELOG.md docs skills/mcp-video/SKILL.md tests/test_rescue_surfaces.py
git commit -m "docs: document the rescue pipeline"
```

- [ ] **Step 9: Produce the implementation receipt**

Record the branch, commit list, focused/full test counts, FFmpeg versions tested, build artifacts, performance report path, leak-audit result, and compatibility risks. Do not publish, push, open a PR, or post issue comments until the repository's public leak audit passes and the user authorizes the external action.

---

## Required Final Review

Before calling implementation complete, use `superpowers:requesting-code-review`, fix all correctness findings, then use `superpowers:verification-before-completion`. The final reviewer must explicitly verify:

- analyzer code never assigns a policy disposition;
- policy code is the only authority for executable eligibility;
- renderer cannot consume raw FFmpeg/filter fragments or non-plan IDs;
- source remains unchanged, and source, plan, policy, dependency, and resume hashes fail closed;
- cancellation and verification failure never promote output;
- master and sharing copy are present on every successful video rescue;
- captions/transcript are sidecars or explicit unavailable artifacts, never burned;
- all metrics have definitions and units;
- CLI failure states return nonzero;
- no existing public surface changed incompatibly;
- no home path, username, credential, or internal process text appears in public artifacts.
