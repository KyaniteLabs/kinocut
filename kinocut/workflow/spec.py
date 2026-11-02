"""Job-spec model + loading for the agent workflow engine.

The spec is an ORDERED job graph (steps run top-to-bottom). Structural
correctness (op allowlist, @ref resolution, backward-reference-only ordering,
per-op params, workspace confinement) is enforced by ``validator``; this module
owns the shape and safe loading of the JSON document itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..ffmpeg_helpers import _validate_input_path
from ..repurpose_policy import RepurposeReleasePolicy
from ._errors import INVALID_WORKFLOW_SPEC, workflow_error
from ..validation_errors import exception_kind


class WorkflowSource(BaseModel):
    """A declared input source (``@sources.<id>``)."""

    model_config = ConfigDict(extra="forbid")

    path: str


class WorkflowOutput(BaseModel):
    """A declared final output target (``@outputs.<id>``)."""

    model_config = ConfigDict(extra="forbid")

    path: str


class WorkflowStep(BaseModel):
    """A single ordered step in the job graph.

    ``inputs`` wires ``src``/``srcs`` @refs to the backing engine; ``params``
    are tunable knobs validated by introspection of that engine's signature;
    ``output`` targets ``@work/<name>`` (intermediate) or ``@outputs.<id>``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    op: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None


class WorkflowVariant(BaseModel):
    """A batch variant that overrides parts of the base declaration."""

    model_config = ConfigDict(extra="forbid")

    id: str
    overrides: dict[str, Any] = Field(default_factory=dict)


class WorkflowSpec(BaseModel):
    """Top-level agent workflow job-spec (``schema_version: 1``)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: str | None = None
    sources: dict[str, WorkflowSource]
    steps: list[WorkflowStep] = Field(default_factory=list)
    outputs: dict[str, WorkflowOutput] = Field(default_factory=dict)
    variants: list[WorkflowVariant] = Field(default_factory=list)
    repurpose_release_policy: RepurposeReleasePolicy | None = None


def validate_spec_path(spec_path: str) -> Path:
    """Resolve and sanity-check the spec file path (must be an existing .json)."""
    if not isinstance(spec_path, str) or not spec_path:
        raise workflow_error("workflow spec path must be a non-empty string", INVALID_WORKFLOW_SPEC)
    if "\x00" in spec_path:
        raise workflow_error("workflow spec path contains null bytes", INVALID_WORKFLOW_SPEC)
    resolved = Path(_validate_input_path(spec_path)).resolve()
    if resolved.suffix.lower() != ".json":
        raise workflow_error("workflow spec must be a JSON file", INVALID_WORKFLOW_SPEC)
    return resolved


def load_spec(resolved: Path) -> dict[str, Any]:
    """Read and JSON-decode a validated spec path into a dict."""
    raw = resolved.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise workflow_error(f"invalid workflow JSON: {exception_kind(exc)}", INVALID_WORKFLOW_SPEC) from None
    if not isinstance(data, dict):
        raise workflow_error("workflow spec must be a JSON object", INVALID_WORKFLOW_SPEC)
    return data


def parse_spec(data: dict[str, Any]) -> WorkflowSpec:
    """Validate the raw dict against the job-spec model (fail-closed on shape)."""
    try:
        return WorkflowSpec.model_validate(data)
    except ValidationError as exc:
        raise workflow_error(
            f"invalid workflow spec: {_summarize_validation_error(exc)}", INVALID_WORKFLOW_SPEC
        ) from None


def _shipped_field_names() -> set[str]:
    """The field names the spec models define.

    A location segment that is one of these is the spec's own shape. Any
    other segment is a key the caller chose — a source name, a parameter
    name — and it is caller data.
    """
    names: set[str] = set()
    for model in (WorkflowSpec, WorkflowStep, WorkflowSource, WorkflowOutput, WorkflowVariant):
        names.update(model.model_fields)
    return names


def _summarize_validation_error(exc: ValidationError) -> str:
    """A short summary of what failed, naming only the spec's own fields.

    The location of a validation error is a path into the caller's
    document, and the free-form maps in it (``sources``, ``outputs``,
    ``params``) are keyed by names the caller chose. Those names are
    caller data, so a segment that is not one of the spec's own field
    names is replaced rather than repeated. The message itself is the
    validation library's own template and carries no value.
    """
    shipped = _shipped_field_names()
    parts: list[str] = []
    for err in exc.errors():
        segments: list[str] = []
        for part in err.get("loc", ()):
            if isinstance(part, int):
                segments.append(str(part))
            elif isinstance(part, str) and part in shipped:
                segments.append(part)
            else:
                segments.append("<key>")
        loc = ".".join(segments)
        parts.append(f"{loc or '<root>'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts[:6])
