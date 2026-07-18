"""Deterministic Timeline IR canonicalization and Render DAG compilation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from kinocut.render_dag import DAGNode, DAGOutput, DAGSource, RenderDAG
from kinocut.timeline_ir.schema import (
    DAG_KIND_BY_IR_KIND,
    IRNode,
    RationalTime,
    TimelineIR,
    ir_error,
)


def canonicalize(ir: TimelineIR) -> bytes:
    return json.dumps(
        ir.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def ir_identity(ir: TimelineIR) -> str:
    return "sha256:" + hashlib.sha256(canonicalize(ir)).hexdigest()


def parse_timeline_ir(raw: dict[str, Any]) -> TimelineIR:
    """Back-read v0 drafts by adding only the formerly implicit schema version."""
    candidate = deepcopy(raw)
    version = candidate.get("ir_schema_version")
    if version is None or (isinstance(version, int) and not isinstance(version, bool) and version == 0):
        candidate["ir_schema_version"] = 1
    elif version != 1 or isinstance(version, bool) or not isinstance(version, int):
        raise ir_error(f"unsupported ir_schema_version: {version!r}")
    return TimelineIR.model_validate(candidate)


def _compile_params(node: IRNode, timebase: RationalTime) -> dict[str, Any]:
    params = dict(node.params)
    if node.kind != "clip":
        return params
    compiled: dict[str, Any] = {}
    if "start" in params:
        compiled["start"] = RationalTime.model_validate(params["start"]).seconds(timebase)
    if "duration" in params:
        duration = RationalTime.model_validate(params["duration"]).seconds(timebase)
        if duration <= 0:
            raise ir_error(f"clip {node.id!r} duration must be positive")
        compiled["duration"] = duration
    return compiled


def compile_ir_to_dag(ir: TimelineIR) -> RenderDAG:
    """Compile declarative editing semantics into the existing planning DAG."""
    compiled_nodes: list[DAGNode] = []
    for node in ir.nodes:
        try:
            compiled_nodes.append(
                DAGNode(
                    id=node.id,
                    kind=DAG_KIND_BY_IR_KIND[node.kind],
                    depends_on=node.depends_on,
                    inputs=node.inputs,
                    params=_compile_params(node, ir.timebase),
                    output=node.output,
                )
            )
        except Exception as exc:
            if hasattr(exc, "code"):
                raise
            raise ir_error(f"timeline node {node.id!r} cannot compile") from exc
    return RenderDAG(
        name=ir.name,
        sources={key: DAGSource(path=value.path) for key, value in ir.sources.items()},
        nodes=tuple(compiled_nodes),
        outputs={key: DAGOutput(path=value.path) for key, value in ir.outputs.items()},
    )
