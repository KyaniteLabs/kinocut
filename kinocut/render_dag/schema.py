"""Frozen closed-kind planning graph contracts (``dag_schema_version: 1``).

The Render DAG is a **planning-only** layer: it describes a render job as a
directed acyclic graph of allowlisted workflow operations and compiles DOWN
into the existing ``schema_version: 1`` workflow spec consumed by the existing
executor. It never executes, never creates a resume cursor, and never alters
synchronous rendering — every behaviour (validation, planning, rendering,
resume, cancellation, restart) is delegated to the existing workflow engine by
producing a byte-identical spec.

Contracts are frozen, unknown-field-rejecting, and fail-closed:

* ``dag_schema_version`` is the frozen integer ``1`` (``True``/``1.0``/``"1"``
  are rejected, mirroring :class:`~kinocut.contracts._common.RecordBase`);
* the node-kind set is the EXACT current ``OP_ADAPTERS`` operation set — a drift
  guard binds the frozen tuple to the live adapter registry at import, so an
  unknown kind fails closed and an added workflow op fails the guard loudly;
* structural validation (unique ids, all dependency/ref resolution, no cycles,
  deterministic topological ordering, confined sources/outputs, canonical
  params) raises ``MCPVideoError`` and never falls back to silent acceptance.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.errors import MCPVideoError
from kinocut.workflow.ops import OP_ADAPTERS

#: Frozen Render DAG schema version. A bump is a new contract, never an edit.
DAG_SCHEMA_VERSION: Literal[1] = 1

# The shared @ref namespaces — identical to the workflow spec's so a compiled
# spec's refs need no translation.
SOURCE_PREFIX = "@sources."
NODE_OUTPUT_PREFIX = "@work/"  # a node's intermediate output is materialized here
OUTPUT_PREFIX = "@outputs."

#: Frozen closed set of DAG node kinds — the EXACT current ``OP_ADAPTERS``
#: operations, in a stable published order. A kind outside this tuple fails
#: closed (``unsupported_workflow_op``); adding a workflow op is a schema bump.
DAG_NODE_KINDS: tuple[str, ...] = (
    "probe",
    "trim",
    "resize",
    "convert",
    "crop",
    "add_text",
    "merge",
    "composite_layers",
    "burn_in",
)

#: Frozen view of the allowlist for O(1) membership + the drift guard.
_DAG_NODE_KIND_SET: frozenset[str] = frozenset(DAG_NODE_KINDS)


def _drift_check() -> None:
    """Bind the frozen kind tuple to the live adapter registry.

    The frozen tuple is the contract; this guard makes a divergence (a workflow
    op added without bumping the DAG schema) fail loudly at import rather than
    silently widening the planning allowlist. It must NEVER widen the tuple —
    the tuple is the authoritative closed set and the registry is checked
    against it.
    """

    live = frozenset(OP_ADAPTERS)
    frozen = _DAG_NODE_KIND_SET
    if live != frozen:
        missing = sorted(frozen - live)
        extra = sorted(live - frozen)
        raise RuntimeError(
            "DAG_NODE_KINDS drifted from OP_ADAPTERS "
            f"(missing adapters: {missing}; unlisted adapters: {extra}); "
            "bump dag_schema_version instead of widening the planning allowlist"
        )


_drift_check()

# Bounded, safe identifiers reused across source/output/node ids. No traversal,
# absolute, NUL, or whitespace — they become @ref and path components.
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"

#: Stable error codes (mirrors the workflow engine's vocabulary).
UNSUPPORTED_DAG_KIND = "unsupported_workflow_op"
INVALID_DAG_SPEC = "invalid_workflow_spec"
UNKNOWN_DAG_REF = "unknown_workflow_ref"
INVALID_DAG_PARAMS = "invalid_workflow_params"
UNSAFE_DAG_PATH = "unsafe_workflow_source"
DAG_CYCLE = "dag_cycle"


def dag_error(message: str, code: str) -> MCPVideoError:
    """Build a fail-closed ``MCPVideoError`` for a Render DAG validation failure."""

    return MCPVideoError(error_type="validation_error", code=code, message=message)


def _validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise dag_error(f"{label} must be a string", INVALID_DAG_SPEC)
    import re

    if re.fullmatch(_ID_PATTERN, value) is None:
        raise dag_error(
            f"{label} {value!r} must match {_ID_PATTERN} (no traversal, spaces, or empty)",
            INVALID_DAG_SPEC,
        )
    return value


def _validate_confined_path(value: Any, label: str) -> str:
    """Reject any source/output path that is not a safe relative posix path.

    Mirrors the workflow validator's confinement rule but without a workspace
    root (the DAG is planning-only): the path must be relative, non-empty, free
    of NUL/control bytes, and contain no traversal/empty/cwd segments.
    """

    if not isinstance(value, str) or not value:
        raise dag_error(f"{label} must be a non-empty string", UNSAFE_DAG_PATH)
    if "\x00" in value or "\\" in value:
        raise dag_error(f"{label} contains null or backslash bytes", UNSAFE_DAG_PATH)
    import os

    candidate = os.path.normpath(value)
    if os.path.isabs(candidate):
        raise dag_error(f"{label} must be a relative path, got absolute {value!r}", UNSAFE_DAG_PATH)
    parts = value.split("/")
    if any(segment in ("", "..", ".") for segment in parts):
        raise dag_error(f"{label} must not contain traversal or empty segments: {value!r}", UNSAFE_DAG_PATH)
    return value


class DAGSource(ValueObject):
    """A declared planning input source (``@sources.<id>``).

    The dict key in :class:`RenderDAG.sources` is the canonical id (mirroring
    ``WorkflowSource``); the value carries only the confined relative path.
    """

    path: str

    @model_validator(mode="after")
    def _validate(self) -> DAGSource:
        _validate_confined_path(self.path, "source path")
        return self


class DAGOutput(ValueObject):
    """A declared planning final-output target (``@outputs.<id>``).

    The dict key in :class:`RenderDAG.outputs` is the canonical id (mirroring
    ``WorkflowOutput``); the value carries only the confined relative path.
    """

    path: str

    @model_validator(mode="after")
    def _validate(self) -> DAGOutput:
        _validate_confined_path(self.path, "output path")
        return self


class DAGNode(ValueObject):
    """One node in the planning DAG; kind is a closed allowlisted operation.

    ``depends_on`` lists node ids that must strictly precede this node; input
    refs of the form ``@work/<node_id>`` imply the same precedence and must
    name a declared dependency. ``output`` is ``@work/<name>`` (intermediate)
    or ``@outputs.<id>`` (final), and is ``None`` only for inspection kinds
    (``probe``) that produce no artifact.
    """

    id: str
    kind: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind_is_allowlisted(cls, value: str) -> str:
        if value not in _DAG_NODE_KIND_SET:
            raise dag_error(
                f"node kind {value!r} is not in the frozen allowlist {list(DAG_NODE_KINDS)}",
                UNSUPPORTED_DAG_KIND,
            )
        return value

    @model_validator(mode="after")
    def _validate(self) -> DAGNode:
        _validate_id(self.id, "node id")
        for dep in self.depends_on:
            _validate_id(dep, f"node {self.id!r} depends_on")
        return self


class RenderDAG(ValueObject):
    """A frozen closed-kind planning graph (``dag_schema_version: 1``).

    ``nodes`` carries the declared declaration order, which is the deterministic
    tie-breaker for topological ordering (see :mod:`kinocut.render_dag.compiler`).
    Validation is fail-closed and structural; it never renders.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    dag_schema_version: Literal[1] = DAG_SCHEMA_VERSION
    name: str | None = Field(default=None, max_length=255)
    sources: dict[str, DAGSource]
    nodes: tuple[DAGNode, ...]
    outputs: dict[str, DAGOutput] = Field(default_factory=dict)

    @field_validator("dag_schema_version", mode="before")
    @classmethod
    def _schema_version_is_strict_int(cls, value: Any) -> Any:
        """Reject coerced versions (``True``, ``"1"``, ``1.0``) before the literal."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise dag_error("dag_schema_version must be the integer 1", INVALID_DAG_SPEC)
        return value

    @field_validator("nodes")
    @classmethod
    def _nodes_nonempty(cls, value: tuple[DAGNode, ...]) -> tuple[DAGNode, ...]:
        if not value:
            raise dag_error("RenderDAG must declare at least one node", INVALID_DAG_SPEC)
        return value

    @model_validator(mode="after")
    def _validate(self) -> RenderDAG:
        for source_id in self.sources:
            _validate_id(source_id, "source id")
        for output_id in self.outputs:
            _validate_id(output_id, "output id")
        from kinocut.render_dag.validation import validate_dag

        validate_dag(self)
        return self
