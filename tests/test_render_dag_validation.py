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
    DAGNode,
    DAGOutput,
    DAGSource,
    RenderDAG,
    compile_dag_to_spec,
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


# --- canonical params --------------------------------------------------------


def test_unknown_param_fails_closed():
    with pytest.raises(MCPVideoError) as exc:
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(
                    id="n",
                    kind="trim",
                    inputs={"src": "@sources.hero"},
                    params={"bogus_param": 1},
                    output="@work/n",
                ),
            ),
        )
    assert exc.value.code == "invalid_workflow_params"


def test_wrong_input_key_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="trim", inputs={"srcs": ["@sources.hero"]}, output="@work/n"),),
        )


def test_single_input_requires_ref_string():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="trim", inputs={"src": 123}, output="@work/n"),),
        )


def test_multi_input_requires_nonempty_ref_list():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="n", kind="merge", inputs={"srcs": "@sources.hero"}, output="@work/n"),),
        )


def test_multi_input_merge_accepts_srcs_list():
    dag = RenderDAG(
        sources={"a": DAGSource(path="a.mp4"), "b": DAGSource(path="b.mp4")},
        nodes=(
            DAGNode(
                id="m",
                kind="merge",
                inputs={"srcs": ["@sources.a", "@sources.b"]},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    compiled = compile_dag_to_spec(dag)
    assert compiled.spec["steps"][0]["inputs"] == {"srcs": ["@sources.a", "@sources.b"]}


def test_burn_in_two_source_binding():
    dag = RenderDAG(
        sources={
            "video": DAGSource(path="video.mp4"),
            "sub": DAGSource(path="sub.srt"),
        },
        nodes=(
            DAGNode(
                id="burn",
                kind="burn_in",
                inputs={"srcs": ["@sources.video", "@sources.sub"]},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    compiled = compile_dag_to_spec(dag)
    step = compiled.spec["steps"][0]
    assert step["op"] == "burn_in"
    assert step["inputs"] == {"srcs": ["@sources.video", "@sources.sub"]}


def test_composite_layers_accepts_canvas_param():
    dag = RenderDAG(
        sources={"bg": DAGSource(path="bg.mp4")},
        nodes=(
            DAGNode(
                id="comp",
                kind="composite_layers",
                inputs={"layers": [{"id": "l1", "type": "video", "src": "@sources.bg"}]},
                params={"canvas": {"width": 640, "height": 360}},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    compiled = compile_dag_to_spec(dag)
    assert compiled.spec["steps"][0]["op"] == "composite_layers"
    assert compiled.spec["steps"][0]["params"] == {"canvas": {"width": 640, "height": 360}}


def test_composite_layer_work_ref_implies_dependency_and_orders():
    """A composite layer src that is a @work/<node> ref must be a declared
    dependency; it feeds the topological order so the compiled step references
    only strictly-earlier work."""

    dag = RenderDAG(
        sources={"bg": DAGSource(path="bg.mp4")},
        nodes=(
            DAGNode(id="trimbg", kind="trim", inputs={"src": "@sources.bg"}, output="@work/trimbg"),
            DAGNode(
                id="comp",
                kind="composite_layers",
                depends_on=("trimbg",),
                inputs={"layers": [{"id": "l1", "type": "video", "src": "@work/trimbg"}]},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    order = topological_order(dag)
    assert order.index("trimbg") < order.index("comp")


# --- composite layer src/mask fail-closed (reuses workflow composite helper) --


def _composite_dag(layers: list) -> RenderDAG:
    return RenderDAG(
        sources={"bg": DAGSource(path="bg.mp4"), "ov": DAGSource(path="ov.mp4")},
        nodes=(
            DAGNode(
                id="comp",
                kind="composite_layers",
                inputs={"layers": layers},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )


def test_composite_layer_raw_path_src_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "bg.mp4"}])


def test_composite_layer_absolute_path_src_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "/abs/bg.mp4"}])


def test_composite_layer_undeclared_source_ref_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "@sources.missing"}])


def test_composite_layer_work_ref_not_in_depends_on_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"bg": DAGSource(path="bg.mp4")},
            nodes=(
                DAGNode(id="trimbg", kind="trim", inputs={"src": "@sources.bg"}, output="@work/trimbg"),
                # references @work/trimbg in a layer but omits it from depends_on
                DAGNode(
                    id="comp",
                    kind="composite_layers",
                    inputs={"layers": [{"id": "l1", "type": "video", "src": "@work/trimbg"}]},
                    output="@outputs.out",
                ),
            ),
            outputs={"out": DAGOutput(path="out.mp4")},
        )


def test_composite_layer_work_ref_to_unknown_node_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "@work/ghost"}])


def test_composite_layer_undeclared_mask_ref_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "@sources.bg", "mask": "@sources.missing"}])


def test_composite_layer_bad_type_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "audio", "src": "@sources.bg"}])


def test_composite_video_layer_missing_src_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video"}])


def test_composite_layer_unknown_field_fails_closed():
    with pytest.raises(MCPVideoError):
        _composite_dag([{"id": "l1", "type": "video", "src": "@sources.bg", "bogus": 1}])


# --- path confinement --------------------------------------------------------


@pytest.mark.parametrize("path", ["/abs/hero.mp4", "../escape.mp4", "./cwd.mp4", "a/../b.mp4", "", "a\\b.mp4"])
def test_unsafe_source_path_fails_closed(path):
    with pytest.raises(DAG_ERROR):
        DAGSource(path=path)


def test_unsafe_output_path_fails_closed():
    with pytest.raises(DAG_ERROR):
        DAGOutput(path="../escape.mp4")


def test_null_byte_path_fails_closed():
    with pytest.raises(DAG_ERROR):
        DAGSource(path="input/hero\x00.mp4")


def test_confined_relative_paths_are_accepted():
    DAGSource(path="input/hero.mp4")
    DAGOutput(path="output/final.mp4")
    DAGSource(path="nested/dir/clip.mp4")


# --- cycles ------------------------------------------------------------------


def test_self_cycle_fails_closed():
    with pytest.raises(MCPVideoError):
        RenderDAG(
            sources={"hero": _src()},
            nodes=(DAGNode(id="a", kind="trim", depends_on=("a",), inputs={"src": "@sources.hero"}, output="@work/a"),),
        )


def test_two_node_cycle_fails_closed():
    with pytest.raises(MCPVideoError) as exc:
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(id="a", kind="trim", depends_on=("b",), inputs={"src": "@sources.hero"}, output="@work/a"),
                DAGNode(
                    id="b",
                    kind="resize",
                    depends_on=("a",),
                    inputs={"src": "@work/a"},
                    output="@work/b",
                ),
            ),
        )
    assert exc.value.code == "dag_cycle"


def test_three_node_cycle_fails_closed():
    with pytest.raises(MCPVideoError) as exc:
        RenderDAG(
            sources={"hero": _src()},
            nodes=(
                DAGNode(id="a", kind="trim", depends_on=("c",), inputs={"src": "@sources.hero"}, output="@work/a"),
                DAGNode(id="b", kind="resize", depends_on=("a",), inputs={"src": "@work/a"}, output="@work/b"),
                DAGNode(id="c", kind="crop", depends_on=("b",), inputs={"src": "@work/b"}, output="@work/c"),
            ),
        )
    assert exc.value.code == "dag_cycle"
