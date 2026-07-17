"""Compile a frozen Render DAG into the existing ``schema_version: 1`` workflow spec.

This is the **compile-down** seam: a planning DAG becomes a byte-identical
workflow job-spec that the existing executor validates, plans, renders, and
resumes exactly as a hand-written spec. The DAG owns no execution, no cursor,
and no receipt lineage of its own — it produces a spec and delegates.

Determinism is the contract. One shared canonical serializer
(:func:`canonical_json`, identical to ``canonical_record_id`` /
``_operation_id``) is used to (a) derive the DAG's identity, (b) serialize the
compiled spec, and (c) compute its ``spec_hash``. Because the same serializer
hashes the compiled spec bytes, the hash equals the executor's whole-file
``sha256(file_bytes)`` when those bytes are written verbatim — so a DAG-compiled
job reuses the existing resume/cancellation/restart path unchanged.

Cache semantics are fail-closed and read-only:

* **stale** — a cached entry whose recorded DAG identity no longer matches the
  current DAG (the plan changed; the cache is a different job) → reject;
* **corrupt** — a cached entry whose recorded ``spec_hash`` does not match the
  serialized bytes, or whose bytes do not parse as a valid spec → reject.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from kinocut.errors import MCPVideoError

from kinocut.render_dag import schema
from kinocut.render_dag.schema import INVALID_DAG_SPEC, RenderDAG, dag_error
from kinocut.render_dag.validation import (
    iter_node_input_refs,
    node_dependency_edges,
    validate_dag,
)
from kinocut.workflow.spec import parse_spec


@dataclass(frozen=True)
class CompiledSpec:
    """A validated DAG lowered to a workflow spec, with its deterministic identity."""

    spec: dict[str, Any]
    spec_bytes: bytes
    spec_hash: str
    dag_identity: str
    order: tuple[str, ...]  # deterministic topological node order

    def write(self, path: str) -> None:
        """Write the canonical spec bytes verbatim so the executor's hash matches."""

        with open(path, "wb") as handle:
            handle.write(self.spec_bytes)


# --- the one shared canonical serializer -------------------------------------


def canonical_json(value: Any) -> bytes:
    """Serialize any JSON value to canonical bytes.

    This is the single serializer shared by DAG identity, spec serialization,
    spec hashing, and the parity tests — sorted keys, compact separators, no
    non-finite floats, UTF-8. It mirrors ``canonical_record_id`` /
    ``_operation_id`` exactly so a compiled spec hashes identically to an
    equivalent hand-written spec.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def serialize_spec(spec: dict[str, Any]) -> bytes:
    """Canonical bytes of a workflow spec dict (the parity-test entry point)."""

    return canonical_json(spec)


def spec_hash(spec: dict[str, Any]) -> str:
    """``sha256:<hex>`` over a workflow spec's canonical bytes."""

    return "sha256:" + hashlib.sha256(serialize_spec(spec)).hexdigest()


def dag_identity(dag: RenderDAG) -> str:
    """``sha256:<hex>`` over a DAG's canonical semantic content.

    The identity covers the schema version, name, sources, nodes (in declared
    order), and outputs — every semantic field. It is the cache key and the
    stale-detection anchor: two DAGs share an identity iff they are logically
    identical, so a changed plan is always a different job.
    """

    payload = dag.model_dump(mode="json")
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


# --- topological ordering ----------------------------------------------------


def topological_order(dag: RenderDAG) -> tuple[str, ...]:
    """Return the deterministic topological node order (declaration-order tie-break).

    Uses Kahn's algorithm: a node becomes ready once every dependency has been
    emitted; ready nodes are emitted in their declared order. This is stable
    and reproducible — the same DAG always yields the same order, and a linear
    hand-written spec that mirrors the declaration order compiles byte-identical.
    Raises ``dag_cycle`` if the validated DAG somehow still has a cycle.
    """

    node_by_id = {node.id: node for node in dag.nodes}
    adjacency = node_dependency_edges(node_by_id)
    in_degree: dict[str, int] = {node.id: len(adjacency[node.id]) for node in dag.nodes}
    # Dependents of each dependency: dep -> nodes that wait on it.
    dependents: dict[str, list[str]] = {node.id: [] for node in dag.nodes}
    for node_id, deps in adjacency.items():
        for dep in deps:
            dependents[dep].append(node_id)

    order: list[str] = []
    # Process nodes in declared order each pass so the tie-break is stable.
    pending = [node.id for node in dag.nodes]
    ready = deque(node_id for node_id in pending if in_degree[node_id] == 0)
    # Keep a declared-position index for a stable ready-emission order.
    declared_index = {node.id: index for index, node in enumerate(dag.nodes)}

    while ready:
        # Emit the earliest-declared ready node (stable tie-break).
        current = min(ready, key=lambda nid: declared_index[nid])
        ready.remove(current)
        order.append(current)
        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    if len(order) != len(dag.nodes):
        raise dag_error("RenderDAG contains a cycle", schema.DAG_CYCLE)
    return tuple(order)


# --- compile-down ------------------------------------------------------------


def _node_to_step(node: schema.DAGNode) -> dict[str, Any]:
    """Lower one DAG node to its canonical workflow step dict.

    ``inputs`` and ``params`` are preserved verbatim (refs already validated);
    ``output`` is omitted for inspection kinds so the step matches the workflow
    model's defaults and a hand-written equivalent serializes byte-identical.
    """

    step: dict[str, Any] = {"id": node.id, "op": node.kind, "inputs": dict(node.inputs)}
    if node.params:
        step["params"] = dict(node.params)
    if node.output is not None:
        step["output"] = node.output
    return step


def compile_dag_to_spec(dag: RenderDAG) -> CompiledSpec:
    """Validate ``dag`` fail-closed and lower it to a workflow spec.

    The DAG is re-validated (structural + allowlist + params) before any step is
    emitted, then deterministically topologically ordered and lowered. The
    result carries the canonical spec bytes and hash (identical to the existing
    executor's whole-file hash when written verbatim) plus the DAG identity used
    for cache staleness. The DAG never executes; this function only plans.
    """

    validate_dag(dag)
    order = topological_order(dag)
    node_by_id = {node.id: node for node in dag.nodes}
    steps = [_node_to_step(node_by_id[node_id]) for node_id in order]
    spec: dict[str, Any] = {
        "schema_version": 1,
        "sources": {sid: {"path": src.path} for sid, src in dag.sources.items()},
        "steps": steps,
        "outputs": {oid: {"path": out.path} for oid, out in dag.outputs.items()},
    }
    if dag.name is not None:
        spec["name"] = dag.name

    # Prove the compiled spec is a valid schema_version:1 workflow spec — this
    # binds the DAG to the existing executor's validation/resume/cancel path.
    try:
        parse_spec(spec)
    except ValidationError as exc:
        raise dag_error(
            f"compiled DAG spec failed workflow validation: {exc}",
            INVALID_DAG_SPEC,
        ) from exc
    _assert_valid_linear_spec(spec, order, node_by_id)

    spec_bytes = serialize_spec(spec)
    digest = "sha256:" + hashlib.sha256(spec_bytes).hexdigest()
    return CompiledSpec(
        spec=spec,
        spec_bytes=spec_bytes,
        spec_hash=digest,
        dag_identity=dag_identity(dag),
        order=order,
    )


def _assert_valid_linear_spec(
    spec: dict[str, Any], order: tuple[str, ...], node_by_id: dict[str, schema.DAGNode]
) -> None:
    """Guarantee every @work ref points strictly earlier in the compiled order.

    The workflow executor enforces backward-reference-only ordering; the DAG's
    topological order already guarantees this, but this is an explicit, cheap
    invariant check that the compiled spec is directly consumable by the
    existing synchronous renderer without reordering.
    """

    position = {node_id: index for index, node_id in enumerate(order)}
    for node_id in order:
        node = node_by_id[node_id]
        for ref in iter_node_input_refs(node):
            if isinstance(ref, str) and ref.startswith(schema.NODE_OUTPUT_PREFIX):
                name = ref[len(schema.NODE_OUTPUT_PREFIX) :]
                if position[name] >= position[node_id]:
                    raise dag_error(
                        f"compiled spec is not backward-reference-only at node {node_id!r}",
                        INVALID_DAG_SPEC,
                    )


# --- fail-closed cache verification ------------------------------------------


@dataclass(frozen=True)
class VerifiedCache:
    """A spec cache entry that matched its DAG identity and hash."""

    spec: dict[str, Any]
    spec_bytes: bytes
    spec_hash: str
    dag_identity: str


def verify_spec_cache(
    dag: RenderDAG,
    spec_bytes: bytes,
    *,
    claimed_dag_identity: str,
    claimed_spec_hash: str,
) -> VerifiedCache:
    """Re-verify a cached compiled spec against the current DAG; fail closed.

    Three independent checks, each fail-closed:

    * **stale** — ``claimed_dag_identity`` must equal :func:`dag_identity` of the
      current ``dag``; a changed plan is a different job;
    * **corrupt (hash)** — ``sha256(spec_bytes)`` must equal
      ``claimed_spec_hash``; tampered or truncated bytes are rejected;
    * **corrupt (shape)** — ``spec_bytes`` must parse into a valid
      ``schema_version: 1`` workflow spec.

    On success the parsed spec, recomputed hash, and identity are returned. The
    cache is read-only: this function never writes, executes, or mutates state.
    """

    current_identity = dag_identity(dag)
    if claimed_dag_identity != current_identity:
        raise dag_error(
            f"stale cache: dag identity {claimed_dag_identity!r} does not match "
            f"current {current_identity!r}; the plan changed — recompile",
            "stale_dag_cache",
        )
    recomputed = "sha256:" + hashlib.sha256(spec_bytes).hexdigest()
    if claimed_spec_hash != recomputed:
        raise dag_error(
            f"corrupt cache: claimed spec_hash {claimed_spec_hash!r} does not match "
            f"recomputed {recomputed!r}; the cached spec bytes were tampered or truncated",
            "corrupt_dag_cache",
        )
    try:
        decoded = json.loads(spec_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise dag_error(
            f"corrupt cache: spec bytes are not valid UTF-8 JSON ({exc})",
            "corrupt_dag_cache",
        ) from exc
    try:
        parse_spec(decoded)
    except (ValidationError, MCPVideoError) as exc:
        raise dag_error(
            f"corrupt cache: spec bytes do not parse as a schema_version:1 spec ({exc})",
            "corrupt_dag_cache",
        ) from exc
    return VerifiedCache(
        spec=decoded,
        spec_bytes=spec_bytes,
        spec_hash=recomputed,
        dag_identity=current_identity,
    )


__all__ = [
    "CompiledSpec",
    "VerifiedCache",
    "canonical_json",
    "compile_dag_to_spec",
    "dag_identity",
    "serialize_spec",
    "spec_hash",
    "topological_order",
    "verify_spec_cache",
]
