"""Structural validation for frozen Render DAG contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from kinocut.limits import MAX_WORKFLOW_STEPS
from kinocut.render_dag.schema import (
    DAG_CYCLE,
    INVALID_DAG_PARAMS,
    INVALID_DAG_SPEC,
    NODE_OUTPUT_PREFIX,
    OUTPUT_PREFIX,
    SOURCE_PREFIX,
    UNKNOWN_DAG_REF,
    DAGNode,
    RenderDAG,
    dag_error,
)
from kinocut.workflow.composite import iter_composite_refs, validate_composite_inputs
from kinocut.workflow.ops import OP_ADAPTERS


def _iter_input_refs(inputs: dict[str, Any]):
    """Yield every leaf ref value in ``inputs`` (single and multi-input)."""
    for value in inputs.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield item
        elif isinstance(value, str):
            yield value


def iter_node_input_refs(node: DAGNode):
    """Yield every input ref, including composite layer src/mask refs."""
    if node.kind == "composite_layers":
        for _key, ref in iter_composite_refs(node.inputs):
            yield ref
    else:
        yield from _iter_input_refs(node.inputs)


def validate_dag(dag: RenderDAG) -> None:
    """Run every fail-closed structural check on a built Render DAG."""
    node_ids = [node.id for node in dag.nodes]
    seen: set[str] = set()
    for node_id in node_ids:
        if node_id in seen:
            raise dag_error(f"duplicate node id: {node_id!r}", INVALID_DAG_SPEC)
        seen.add(node_id)
    if len(node_ids) > MAX_WORKFLOW_STEPS:
        raise dag_error(
            f"RenderDAG declares {len(node_ids)} nodes; the maximum is {MAX_WORKFLOW_STEPS}",
            INVALID_DAG_SPEC,
        )
    source_ids = set(dag.sources)
    output_ids = set(dag.outputs)
    node_by_id = {node.id: node for node in dag.nodes}

    work_names_all = {
        node.output[len(NODE_OUTPUT_PREFIX) :]
        for node in dag.nodes
        if isinstance(node.output, str) and node.output.startswith(NODE_OUTPUT_PREFIX)
    }
    work_outputs: dict[str, str] = {}
    for node in dag.nodes:
        for dep in node.depends_on:
            if dep not in node_by_id:
                raise dag_error(f"node {node.id!r} depends_on unknown node {dep!r}", UNKNOWN_DAG_REF)
            if dep == node.id:
                raise dag_error(f"node {node.id!r} depends_on itself", DAG_CYCLE)
        _validate_node_op(node)
        if node.kind == "composite_layers":
            _validate_composite_layers(node, source_ids, work_names_all)
        _validate_node_inputs(node, source_ids, node_by_id)
        _validate_node_output(node, output_ids, work_outputs)
    _reject_cycles(node_by_id)


def _validate_node_op(node: DAGNode) -> None:
    adapter = OP_ADAPTERS[node.kind]
    expected_key = adapter.input_key
    if not isinstance(node.inputs, dict) or not node.inputs:
        raise dag_error(
            f"node {node.id!r} requires an 'inputs' object with key {expected_key!r}",
            INVALID_DAG_SPEC,
        )
    extra = sorted(set(node.inputs) - {expected_key})
    if extra:
        raise dag_error(
            f"node {node.id!r} ({node.kind}) has unexpected input key(s) {extra}; expected only {expected_key!r}",
            INVALID_DAG_SPEC,
        )
    input_value = node.inputs[expected_key]
    if expected_key == "srcs":
        if (
            not isinstance(input_value, list)
            or not input_value
            or not all(isinstance(ref, str) and ref for ref in input_value)
        ):
            raise dag_error(
                f"node {node.id!r} input {expected_key!r} must be a non-empty list of refs",
                INVALID_DAG_SPEC,
            )
    elif node.kind != "composite_layers" and (not isinstance(input_value, str) or not input_value):
        raise dag_error(
            f"node {node.id!r} input {expected_key!r} must be a non-empty ref string",
            INVALID_DAG_SPEC,
        )
    if not isinstance(node.params, dict):
        raise dag_error(f"node {node.id!r} params must be an object", INVALID_DAG_PARAMS)
    accepted = adapter.accepted_params()
    unknown = sorted(set(node.params) - accepted)
    if unknown:
        raise dag_error(
            f"node {node.id!r} ({node.kind}) has params the engine does not accept: {unknown}; "
            f"accepted: {sorted(accepted)}",
            INVALID_DAG_PARAMS,
        )
    adapter.validate_param_values(node.params, node.id)


def _validate_composite_layers(node: DAGNode, source_ids: set[str], work_produced: set[str]) -> None:
    step = SimpleNamespace(id=node.id, inputs=node.inputs)
    validate_composite_inputs(step, source_ids, work_produced)


def _validate_node_inputs(node: DAGNode, source_ids: set[str], node_by_id: dict[str, DAGNode]) -> None:
    for ref in iter_node_input_refs(node):
        if not isinstance(ref, str) or not ref:
            raise dag_error(
                f"node {node.id!r} has a non-string or empty input reference",
                INVALID_DAG_SPEC,
            )
        if ref.startswith(SOURCE_PREFIX):
            source_id = ref[len(SOURCE_PREFIX) :]
            if source_id not in source_ids:
                raise dag_error(
                    f"node {node.id!r} references undeclared source {ref!r}",
                    UNKNOWN_DAG_REF,
                )
        elif ref.startswith(NODE_OUTPUT_PREFIX):
            name = ref[len(NODE_OUTPUT_PREFIX) :]
            if not name:
                raise dag_error(
                    f"node {node.id!r} has an empty @work/ input reference",
                    INVALID_DAG_SPEC,
                )
            target = node_by_id.get(name)
            if target is None:
                raise dag_error(
                    f"node {node.id!r} references {ref!r} which is no node's output",
                    UNKNOWN_DAG_REF,
                )
            if target.output != ref:
                raise dag_error(
                    f"node {node.id!r} references {ref!r} but node {name!r} does not produce it",
                    UNKNOWN_DAG_REF,
                )
            if name not in node.depends_on:
                raise dag_error(
                    f"node {node.id!r} references {ref!r} but does not declare it in depends_on",
                    UNKNOWN_DAG_REF,
                )
        elif ref.startswith(OUTPUT_PREFIX):
            raise dag_error(
                f"node {node.id!r} references {ref!r}; @outputs.<id> is a target, not a step input",
                UNKNOWN_DAG_REF,
            )
        elif ref.startswith("@"):
            raise dag_error(
                f"node {node.id!r} uses unknown ref namespace {ref!r}",
                UNKNOWN_DAG_REF,
            )
        else:
            raise dag_error(
                f"node {node.id!r} input {ref!r} must be an @sources./@work/ ref",
                UNKNOWN_DAG_REF,
            )


def _validate_node_output(node: DAGNode, output_ids: set[str], work_outputs: dict[str, str]) -> None:
    adapter = OP_ADAPTERS[node.kind]
    if not adapter.has_output:
        if node.output is not None:
            raise dag_error(
                f"node {node.id!r} kind {node.kind!r} produces no output; remove 'output'",
                INVALID_DAG_SPEC,
            )
        return
    if node.output is None:
        raise dag_error(
            f"node {node.id!r} kind {node.kind!r} requires an output (@work/<name> or @outputs.<id>)",
            INVALID_DAG_SPEC,
        )
    if not isinstance(node.output, str):
        raise dag_error(f"node {node.id!r} output must be a string", INVALID_DAG_SPEC)
    if node.output.startswith(NODE_OUTPUT_PREFIX):
        name = node.output[len(NODE_OUTPUT_PREFIX) :]
        if not name:
            raise dag_error(f"node {node.id!r} has an empty @work/ output name", INVALID_DAG_SPEC)
        if name != node.id:
            raise dag_error(
                f"node {node.id!r} @work output must be named after its id (@work/{node.id}); got {node.output!r}",
                INVALID_DAG_SPEC,
            )
        if name in work_outputs:
            raise dag_error(
                f"node {node.id!r} reuses the @work output name {name!r}",
                INVALID_DAG_SPEC,
            )
        work_outputs[name] = node.id
    elif node.output.startswith(OUTPUT_PREFIX):
        output_id = node.output[len(OUTPUT_PREFIX) :]
        if output_id not in output_ids:
            raise dag_error(
                f"node {node.id!r} writes to undeclared output {node.output!r}",
                UNKNOWN_DAG_REF,
            )
    else:
        raise dag_error(
            f"node {node.id!r} output must be @work/<name> or @outputs.<id>, got {node.output!r}",
            INVALID_DAG_SPEC,
        )


def node_dependency_edges(node_by_id: dict[str, DAGNode]) -> dict[str, set[str]]:
    """Return dependency adjacency from declarations and nested input refs."""
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    for node_id, node in node_by_id.items():
        adjacency[node_id].update(node.depends_on)
        for ref in iter_node_input_refs(node):
            if isinstance(ref, str) and ref.startswith(NODE_OUTPUT_PREFIX):
                name = ref[len(NODE_OUTPUT_PREFIX) :]
                if name in node_by_id:
                    adjacency[node_id].add(name)
    return adjacency


def _reject_cycles(node_by_id: dict[str, DAGNode]) -> None:
    adjacency = node_dependency_edges(node_by_id)
    white, grey, black = 0, 1, 2
    colour: dict[str, int] = {node_id: white for node_id in node_by_id}

    def visit(start: str) -> None:
        stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        colour[start] = grey
        while stack:
            node_id, path = stack[-1]
            for dep in adjacency[node_id]:
                if colour[dep] == grey:
                    cycle = " -> ".join((*path, dep))
                    raise dag_error(f"RenderDAG contains a cycle: {cycle}", DAG_CYCLE)
                if colour[dep] == white:
                    colour[dep] = grey
                    stack.append((dep, (*path, dep)))
                    break
            else:
                colour[node_id] = black
                stack.pop()

    for node_id in node_by_id:
        if colour[node_id] == white:
            visit(node_id)
