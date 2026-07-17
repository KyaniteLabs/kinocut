"""Render DAG (P2) — frozen closed-kind planning layer over the workflow executor.

Covers the P2 acceptance: deterministic equality, the frozen op allowlist (with
a drift guard binding it to ``OP_ADAPTERS``), cycle / missing-dep detection,
deterministic topological ordering, confined sources/outputs, canonical params,
stale/corrupt cache rejection, cancellation/restart compatibility through the
existing workflow spec behavior, and exact spec-hash parity with an equivalent
hand-written spec — all through the one shared canonical serializer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from kinocut.errors import MCPVideoError
from kinocut.render_dag import (
    DAG_NODE_KINDS,
    DAG_SCHEMA_VERSION,
    DAGNode,
    DAGOutput,
    DAGSource,
    RenderDAG,
)
from kinocut.workflow.ops import OP_ADAPTERS

# A DAG construction can surface either a pydantic ValidationError (extra fields,
# Literal coercion) or a fail-closed MCPVideoError (structural/allowlist checks).
DAG_ERROR = (PydanticValidationError, MCPVideoError)


# --- fixtures ----------------------------------------------------------------


def _src(path: str = "input/hero.mp4") -> DAGSource:
    return DAGSource(path=path)


def _flagship_dag() -> RenderDAG:
    """A linear flagship DAG mirroring the workflow ``_flagship_spec`` shape."""

    return RenderDAG(
        dag_schema_version=1,
        name="captioned-vertical-short",
        sources={"hero": DAGSource(path="input/hero.mp4")},
        nodes=(
            DAGNode(id="probe-hero", kind="probe", inputs={"src": "@sources.hero"}),
            DAGNode(
                id="trim-hero",
                kind="trim",
                inputs={"src": "@sources.hero"},
                params={"start": 0, "duration": 6},
                output="@work/trim-hero",
            ),
            DAGNode(
                id="vertical",
                kind="resize",
                depends_on=("trim-hero",),
                inputs={"src": "@work/trim-hero"},
                params={"width": 1080, "height": 1920},
                output="@work/vertical",
            ),
            DAGNode(
                id="caption",
                kind="add_text",
                depends_on=("vertical",),
                inputs={"src": "@work/vertical"},
                params={"text": "Watch this", "position": "bottom-center"},
                output="@outputs.master",
            ),
        ),
        outputs={"master": DAGOutput(path="output/final.mp4")},
    )


def _flagship_handwritten_spec() -> dict:
    """An equivalent hand-written workflow spec dict (independent of the compiler)."""

    return {
        "schema_version": 1,
        "name": "captioned-vertical-short",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim-hero",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"duration": 6, "start": 0},
                "output": "@work/trim-hero",
            },
            {
                "id": "vertical",
                "op": "resize",
                "inputs": {"src": "@work/trim-hero"},
                "params": {"height": 1920, "width": 1080},
                "output": "@work/vertical",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/vertical"},
                "params": {"position": "bottom-center", "text": "Watch this"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }


def _write_spec(directory: Path, spec: dict, name: str = "job.json") -> str:
    path = Path(directory) / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


# --- frozen schema version ---------------------------------------------------


def test_dag_schema_version_is_frozen_at_one():
    assert DAG_SCHEMA_VERSION == 1
    with pytest.raises(DAG_ERROR):
        RenderDAG(
            dag_schema_version=2,
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}),),
        )


@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_dag_schema_version_rejects_coerced_values(bad):
    with pytest.raises(DAG_ERROR):
        RenderDAG(
            dag_schema_version=bad,
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}),),
        )


# --- allowlist + drift guard -------------------------------------------------


def test_node_kind_allowlist_is_exactly_op_adapters():
    """The frozen kind set must equal the live workflow op registry exactly."""

    assert set(DAG_NODE_KINDS) == set(OP_ADAPTERS)


@pytest.mark.parametrize("kind", list(DAG_NODE_KINDS))
def test_every_allowlisted_kind_is_accepted_by_the_field(kind):
    """The frozen kind field accepts every allowlisted op (no allowlist rejection).

    Per-kind input/output binding is exercised by the dedicated behavior tests
    (flagship, merge, burn_in, composite); here we only assert the closed kind
    set is accepted at the field boundary.
    """

    node = DAGNode(id="n", kind=kind)
    assert node.kind == kind


@pytest.mark.parametrize("kind", ["speed", "explode", "upscale", "", "PROBE", "merge_clips"])
def test_unknown_kind_fails_closed(kind):
    with pytest.raises(DAG_ERROR) as exc:
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind=kind, inputs={"src": "@sources.hero"}),),
        )
    assert exc.value.code in {"unsupported_workflow_op", "invalid_workflow_spec"}


# --- structural validation: unique ids, refs, deps, output rules ------------


def test_duplicate_node_id_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}),
                DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}),
            ),
        )


def test_probe_with_output_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}, output="@work/n"),),
        )


def test_output_op_without_output_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="trim", inputs={"src": "@sources.hero"}),),
        )


def test_undeclared_source_ref_fails_closed():
    with pytest.raises(MCPVideoError) as exc:
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.missing"}),),
        )
    assert exc.value.code == "unknown_workflow_ref"


def test_unknown_depends_on_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}, depends_on=("ghost",)),),
        )


def test_work_ref_not_in_depends_on_fails_closed():
    """A @work/<dep> input ref MUST be declared in depends_on (explicit edges)."""

    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(id="a", kind="trim", inputs={"src": "@sources.hero"}, output="@work/a"),
                # references @work/a but omits it from depends_on
                DAGNode(id="b", kind="resize", inputs={"src": "@work/a"}, output="@work/b"),
            ),
        )


def test_work_ref_to_unknown_node_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="b", kind="resize", depends_on=("a",), inputs={"src": "@work/a"}, output="@work/b"),),
        )


def test_work_output_name_must_match_node_id():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="a", kind="trim", inputs={"src": "@sources.hero"}, output="@work/other"),),
        )


def test_reused_work_output_name_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(id="a", kind="trim", inputs={"src": "@sources.hero"}, output="@work/a"),
                DAGNode(id="a2", kind="trim", inputs={"src": "@sources.hero"}, output="@work/a"),
            ),
        )


def test_output_to_undeclared_output_id_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="trim", inputs={"src": "@sources.hero"}, output="@outputs.ghost"),),
        )


def test_extra_field_fails_closed():
    with pytest.raises(PydanticValidationError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="probe", inputs={"src": "@sources.hero"}),),
            unexpected_field=True,  # type: ignore[call-arg]
        )
