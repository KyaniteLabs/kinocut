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
from ._errors import INVALID_WORKFLOW_SPEC, workflow_error


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
        raise workflow_error(f"invalid workflow JSON: {exc}", INVALID_WORKFLOW_SPEC) from None
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


def _summarize_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        parts.append(f"{loc or '<root>'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts[:6])
