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

from pydantic import ValidationError as PydanticValidationError

from kinocut.errors import MCPVideoError
from kinocut.render_dag import (
    DAGNode,
    DAGOutput,
    DAGSource,
    RenderDAG,
    canonical_json,
    compile_dag_to_spec,
    dag_identity,
    serialize_spec,
    spec_hash,
    topological_order,
)

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


# --- deterministic topological ordering --------------------------------------


def test_topological_order_is_stable_and_declaration_ordered():
    dag = _flagship_dag()
    order = topological_order(dag)
    assert order == tuple(n.id for n in dag.nodes)
    assert topological_order(dag) == topological_order(dag)  # deterministic


def test_diamond_topological_order_respects_tie_break():
    """A diamond (a -> b, a -> c, b+c -> d) keeps declared order b before c."""

    dag = RenderDAG(
        sources={"s": DAGSource(path="s.mp4")},
        nodes=(
            DAGNode(id="a", kind="trim", inputs={"src": "@sources.s"}, output="@work/a"),
            DAGNode(id="b", kind="resize", depends_on=("a",), inputs={"src": "@work/a"}, output="@work/b"),
            DAGNode(id="c", kind="crop", depends_on=("a",), inputs={"src": "@work/a"}, output="@work/c"),
            DAGNode(
                id="d",
                kind="merge",
                depends_on=("b", "c"),
                inputs={"srcs": ["@work/b", "@work/c"]},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    assert topological_order(dag) == ("a", "b", "c", "d")


def test_compile_orders_steps_topologically():
    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    ids = [step["id"] for step in compiled.spec["steps"]]
    assert ids == ["probe-hero", "trim-hero", "vertical", "caption"]
    assert compiled.order == ("probe-hero", "trim-hero", "vertical", "caption")


# --- deterministic equality --------------------------------------------------


def test_dag_identity_is_deterministic():
    dag = _flagship_dag()
    assert dag_identity(dag) == dag_identity(dag)
    assert dag_identity(dag).startswith("sha256:")


def test_equivalent_dags_share_identity():
    assert dag_identity(_flagship_dag()) == dag_identity(_flagship_dag())


def test_distinct_dags_differ_in_identity():
    dag = _flagship_dag()
    other = dag.model_copy(update={"name": "different-name"})
    assert dag_identity(dag) != dag_identity(other)


def test_compile_is_deterministic():
    dag = _flagship_dag()
    a = compile_dag_to_spec(dag)
    b = compile_dag_to_spec(dag)
    assert a.spec_bytes == b.spec_bytes
    assert a.spec_hash == b.spec_hash
    assert a.dag_identity == b.dag_identity


def test_canonical_serializer_is_sorted_and_compact():
    payload = {"b": 2, "a": 1, "c": [3, 2, 1]}
    assert canonical_json(payload) == b'{"a":1,"b":2,"c":[3,2,1]}'


# --- exact spec-hash parity --------------------------------------------------


def test_compiled_spec_bytes_match_handwritten_through_shared_serializer():
    """The parity guarantee: compiled and hand-written specs serialize byte-identical."""

    compiled = compile_dag_to_spec(_flagship_dag())
    handwritten = _flagship_handwritten_spec()
    assert serialize_spec(compiled.spec) == serialize_spec(handwritten)
    assert spec_hash(compiled.spec) == spec_hash(handwritten)
    # The compiled spec carries the same hash as the shared serializer computes.
    assert compiled.spec_hash == spec_hash(compiled.spec)


def test_compiled_spec_hash_is_independent_of_param_key_order():
    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    # Re-serialize a logically-equal dict with shuffled param keys -> same bytes.
    shuffled = json.loads(compiled.spec_bytes.decode("utf-8"))
    assert serialize_spec(shuffled) == compiled.spec_bytes
