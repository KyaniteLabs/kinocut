"""Strict persisted plans for human-reviewed shorts workflows."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path
from .models import CandidateMoment, TranscriptSegment, TranscriptWord


__all__ = [
    "IntakeReport",
    "RenderRecord",
    "ReviewAction",
    "ReviewDecision",
    "ShortsPlan",
    "ShortsPlanStatus",
    "load_shorts_plan",
    "save_shorts_plan",
]


class _StrictModel(BaseModel):
    """Frozen plan model."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


_JOB_ID_PATTERN = r"^shorts_[0-9a-f]{16}$"
_PLAN_FILENAME_RE = re.compile(r"^shorts_[0-9a-f]{16}\.plan\.json$")


ReviewAction = Literal[
    "preview",
    "approve",
    "reject",
    "trim",
    "title_hook_edit",
    "sensitive_unsuitable",
]

ShortsPlanStatus = Literal["review_required", "reviewed", "rendered", "packaged"]


class IntakeReport(_StrictModel):
    """Source-media facts captured at proposal time."""

    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration: float = Field(gt=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio_available: bool
    format: str | None = None
    problems: tuple[str, ...] = ()


class ReviewDecision(_StrictModel):
    """One append-only human review record."""

    candidate_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    action: ReviewAction
    start: float | None = Field(default=None, ge=0.0)
    end: float | None = Field(default=None, gt=0.0)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    hook: str | None = Field(default=None, min_length=1, max_length=240)
    sensitive: bool | None = None
    unsuitable: bool | None = None
    evidence_ref: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_action_shape(self) -> ReviewDecision:
        if self.action == "trim":
            if self.start is None or self.end is None or self.end <= self.start:
                raise ValueError("trim decisions require 0 <= start < end")
            forbidden = ("title", "hook", "sensitive", "unsuitable")
            if any(getattr(self, name) is not None for name in forbidden):
                raise ValueError("trim decisions must not carry title/hook/sensitive/unsuitable")
        elif self.action == "title_hook_edit":
            if self.title is None and self.hook is None:
                raise ValueError("title_hook_edit decisions require title or hook")
            if self.start is not None or self.end is not None:
                raise ValueError("title_hook_edit decisions must not carry start/end")
        elif self.action == "sensitive_unsuitable":
            if self.sensitive is None and self.unsuitable is None:
                raise ValueError("sensitive_unsuitable decisions require sensitive or unsuitable")
            if any(getattr(self, name) is not None for name in ("start", "end", "title", "hook")):
                raise ValueError("sensitive_unsuitable decisions must not carry trim/title fields")
        else:
            if any(
                getattr(self, name) is not None for name in ("start", "end", "title", "hook", "sensitive", "unsuitable")
            ):
                raise ValueError(f"{self.action} decisions must not carry extra fields")
        return self


class RenderRecord(_StrictModel):
    """One platform draft produced by the render stage."""

    candidate_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    platform: Literal["youtube-shorts", "instagram-reel"]
    output_path: str = Field(min_length=1)
    render_digest: str = Field(pattern=r"^[0-9a-f]{16}$")
    editable_subtitles: str = Field(min_length=1)
    thumbnail_path: str = Field(min_length=1)
    cache_hit: bool = False


class ShortsPlan(_StrictModel):
    """Persisted receipt consumed by downstream workflow stages."""

    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=_JOB_ID_PATTERN)
    status: ShortsPlanStatus = "review_required"
    project_dir: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    intake: IntakeReport
    platforms: tuple[Literal["youtube-shorts", "instagram-reel"], ...]
    config: dict[str, Any]
    transcript: tuple[TranscriptSegment, ...]
    proposals: tuple[CandidateMoment, ...]
    decisions: tuple[ReviewDecision, ...] = ()
    renders: tuple[RenderRecord, ...] = ()
    package_manifests: tuple[str, ...] = ()
    transcript_words: tuple[TranscriptWord, ...] = ()
    external_posting: Literal[False] = False

    @model_validator(mode="after")
    def _validate_invariants(self) -> ShortsPlan:
        if not self.platforms:
            raise ValueError("shorts plan must list at least one platform")
        if not self.proposals:
            raise ValueError("shorts plan must contain at least one proposal")
        proposal_ids = {item.candidate_id for item in self.proposals}
        if len(proposal_ids) != len(self.proposals):
            raise ValueError("shorts plan proposals must have unique candidate ids")
        for decision in self.decisions:
            if decision.candidate_id not in proposal_ids:
                raise ValueError(f"decision references unknown candidate {decision.candidate_id!r}")
        for render in self.renders:
            if render.candidate_id not in proposal_ids:
                raise ValueError(f"render references unknown candidate {render.candidate_id!r}")
            if render.platform not in self.platforms:
                raise ValueError(f"render platform {render.platform!r} is not in plan.platforms")
        if self.external_posting is not False:
            raise ValueError("external_posting must remain False")
        return self


def _plan_error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {cause} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


def _plan_filename(plan: ShortsPlan) -> str:
    return f"{plan.job_id}.plan.json"


def _candidate_plan_paths(root: str) -> list[str]:
    """Return sorted plan files under the root and its shorts directory."""
    if not os.path.isdir(root):
        return []
    primary = sorted(entry for entry in os.listdir(root) if _PLAN_FILENAME_RE.match(entry))
    nested_dir = os.path.join(root, "shorts")
    nested = []
    if os.path.isdir(nested_dir):
        nested = sorted(
            os.path.join("shorts", entry) for entry in os.listdir(nested_dir) if _PLAN_FILENAME_RE.match(entry)
        )
    return [os.path.join(root, entry) for entry in (*primary, *nested)]


def _resolve_plan_path(plan_path_or_dir: str) -> str:
    if os.path.isfile(plan_path_or_dir):
        return _validate_artifact_path(plan_path_or_dir)
    if os.path.isdir(plan_path_or_dir):
        candidates = _candidate_plan_paths(os.path.realpath(plan_path_or_dir))
        if len(candidates) == 1:
            return _validate_artifact_path(candidates[0])
        code = "shorts_plan_not_found" if not candidates else "shorts_plan_ambiguous"
        raise _plan_error(
            "The saved shorts plan lookup was not exact.",
            code=code,
            cause=f"Found {len(candidates)} matching plans under {plan_path_or_dir!r}.",
            recovery="Pass an exact plan path or a directory containing one plan.",
        )
    raise _plan_error(
        "The saved shorts plan could not be found.",
        code="shorts_plan_not_found",
        cause=f"{plan_path_or_dir!r} is not a plan file or directory.",
        recovery="Pass an exact plan path or a directory containing one plan.",
    )


def _plan_to_json(plan: ShortsPlan) -> str:
    """Render a plan to canonical JSON."""
    payload = plan.model_dump(mode="json")
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _safe_output_dir(plan: ShortsPlan) -> str:
    requested = Path(plan.output_dir).expanduser().absolute()
    resolved = os.path.realpath(_validate_artifact_path(str(requested)))
    project_root = os.path.realpath(os.path.expanduser(plan.project_dir))
    has_symlink = any(path.is_symlink() for path in (requested, *requested.parents))
    if has_symlink or os.path.commonpath((project_root, resolved)) != project_root:
        raise _plan_error(
            "The plan output path is unsafe.",
            code="unsafe_path",
            cause=str(requested),
            recovery="Choose a real directory inside project_dir.",
        )
    return resolved


def save_shorts_plan(plan: ShortsPlan) -> ShortsPlan:
    """Persist a plan atomically."""
    if not isinstance(plan, ShortsPlan):
        raise _plan_error(
            "save_shorts_plan requires a strict ShortsPlan.",
            code="invalid_plan",
            cause=f"got {type(plan).__name__!r}.",
            recovery="Construct the plan with ShortsPlan.model_validate(...) first.",
        )
    safe_output_dir = _safe_output_dir(plan)
    os.makedirs(safe_output_dir, exist_ok=True)
    target = os.path.join(safe_output_dir, _plan_filename(plan))
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=safe_output_dir, delete=False, encoding="utf-8") as handle:
            temp_path = handle.name
            handle.write(_plan_to_json(plan))
        os.replace(temp_path, target)
    except Exception:
        if temp_path and os.path.lexists(temp_path):
            os.unlink(temp_path)
        raise
    return plan


def load_shorts_plan(plan_path_or_dir: str) -> ShortsPlan:
    """Load one exact, unambiguous, strictly valid plan."""
    plan_path = _resolve_plan_path(plan_path_or_dir)
    try:
        with open(plan_path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        raise _plan_error(
            "The saved shorts plan could not be read.",
            code="shorts_plan_not_found",
            cause=str(exc),
            recovery="Restore the plan file or re-run discovery to regenerate it.",
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _plan_error(
            "The saved shorts plan is not valid JSON.",
            code="shorts_plan_malformed",
            cause=f"{exc.msg} at line {exc.lineno}, column {exc.colno}.",
            recovery="Restore the plan from a previous good backup or rerun discovery.",
        ) from exc
    try:
        return ShortsPlan.model_validate(payload)
    except Exception as exc:  # pydantic.ValidationError or coercion failure
        raise _plan_error(
            "The saved shorts plan failed strict validation.",
            code="shorts_plan_malformed",
            cause=str(exc).splitlines()[0] if str(exc) else "unknown validation failure",
            recovery="Restore the plan from a previous good backup or rerun discovery.",
        ) from exc
