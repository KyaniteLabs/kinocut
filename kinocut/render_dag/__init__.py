"""Render DAG — a frozen closed-kind planning layer over the workflow executor.

This package is **planning-only**. A :class:`~kinocut.render_dag.schema.RenderDAG`
describes a render job as a directed acyclic graph of allowlisted workflow
operations and compiles DOWN into the existing ``schema_version: 1`` workflow
spec (see :func:`~kinocut.render_dag.compiler.compile_dag_to_spec`). It never
executes, never creates a resume cursor, and never alters synchronous rendering
or the public tool/command surface — the compiled spec is consumed by the
existing executor unchanged.

The module is internal: no MCP/CLI/client registration. Public-graduation is a
separately approved slice.
"""

from __future__ import annotations

from kinocut.render_dag.compiler import (
    CompiledSpec,
    VerifiedCache,
    canonical_json,
    compile_dag_to_spec,
    dag_identity,
    serialize_spec,
    spec_hash,
    topological_order,
    verify_spec_cache,
)
from kinocut.render_dag.schema import (
    DAG_SCHEMA_VERSION,
    DAG_NODE_KINDS,
    DAGNode,
    DAGOutput,
    DAGSource,
    RenderDAG,
)
from kinocut.render_dag.validation import validate_dag

__all__ = [
    "DAG_NODE_KINDS",
    "DAG_SCHEMA_VERSION",
    "CompiledSpec",
    "DAGNode",
    "DAGOutput",
    "DAGSource",
    "RenderDAG",
    "VerifiedCache",
    "canonical_json",
    "compile_dag_to_spec",
    "dag_identity",
    "serialize_spec",
    "spec_hash",
    "topological_order",
    "validate_dag",
    "verify_spec_cache",
]
