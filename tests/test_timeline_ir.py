"""Declarative Timeline IR compile-down contracts."""

import pytest

from kinocut.errors import MCPVideoError
from kinocut.render_dag import RenderDAG
from kinocut.timeline_ir import (
    IRNode,
    IROutput,
    IRSource,
    RationalTime,
    TimelineIR,
    canonicalize,
    compile_ir_to_dag,
    ir_identity,
    parse_timeline_ir,
)


def _ir() -> TimelineIR:
    return TimelineIR(
        name="edit",
        timebase=RationalTime(numerator=1, denominator=24),
        sources={"hero": IRSource(path="input/hero.mp4")},
        nodes=(
            IRNode(
                id="clip",
                kind="clip",
                inputs={"src": "@sources.hero"},
                params={
                    "start": {"numerator": 24, "denominator": 1},
                    "duration": {"numerator": 48, "denominator": 1},
                },
                output="@work/clip",
            ),
            IRNode(
                id="text",
                kind="text",
                depends_on=("clip",),
                inputs={"src": "@work/clip"},
                params={"text": "Hello"},
                output="@outputs.master",
            ),
        ),
        outputs={"master": IROutput(path="output/final.mp4")},
    )


def test_canonical_identity_is_deterministic():
    ir = _ir()
    assert canonicalize(ir) == canonicalize(ir)
    assert ir_identity(ir) == ir_identity(_ir())
    assert ir_identity(ir).startswith("sha256:")


def test_rational_time_must_be_reduced():
    with pytest.raises(MCPVideoError):
        RationalTime(numerator=2, denominator=2)


def test_rational_time_rejects_invalid_bounds():
    with pytest.raises(Exception):
        RationalTime(numerator=-1, denominator=1)
    with pytest.raises(Exception):
        RationalTime(numerator=0, denominator=0)


def test_compile_maps_declarative_semantics_to_valid_dag():
    dag = compile_ir_to_dag(_ir())
    assert isinstance(dag, RenderDAG)
    assert [node.kind for node in dag.nodes] == ["trim", "add_text"]
    assert dag.nodes[0].params == {"start": 1.0, "duration": 2.0}


def test_compile_is_deterministic():
    assert compile_ir_to_dag(_ir()) == compile_ir_to_dag(_ir())


def test_unknown_semantics_fail_before_compile():
    with pytest.raises(MCPVideoError):
        IRNode(
            id="clip",
            kind="clip",
            inputs={"src": "@sources.hero"},
            params={"speed": 2},
            output="@work/clip",
        )


def test_ambiguous_zero_duration_fails_closed():
    ir = _ir()
    bad = ir.model_copy(
        update={
            "nodes": (
                ir.nodes[0].model_copy(update={"params": {"duration": {"numerator": 0, "denominator": 1}}}),
                ir.nodes[1],
            )
        }
    )
    with pytest.raises(MCPVideoError):
        compile_ir_to_dag(bad)


def test_unsafe_source_path_fails_closed():
    with pytest.raises(MCPVideoError):
        IRSource(path="../escape.mp4")


def test_back_read_adds_only_implicit_version():
    raw = _ir().model_dump(mode="json")
    raw.pop("ir_schema_version")
    migrated = parse_timeline_ir(raw)
    assert migrated.ir_schema_version == 1
    assert migrated.nodes == _ir().nodes
    assert migrated.sources == _ir().sources


def test_unknown_future_version_fails_closed():
    raw = _ir().model_dump(mode="json")
    raw["ir_schema_version"] = 2
    with pytest.raises(MCPVideoError):
        parse_timeline_ir(raw)


@pytest.mark.parametrize("bad_version", [False, 0.0, "0"])
def test_migration_rejects_coerced_versions(bad_version):
    raw = _ir().model_dump(mode="json")
    raw["ir_schema_version"] = bad_version
    with pytest.raises(MCPVideoError):
        parse_timeline_ir(raw)


def test_duplicate_and_missing_dependencies_fail_closed():
    ir = _ir()
    with pytest.raises(MCPVideoError):
        TimelineIR(
            sources=ir.sources,
            nodes=(ir.nodes[0], ir.nodes[0]),
        )
    with pytest.raises(MCPVideoError):
        TimelineIR(
            sources=ir.sources,
            nodes=(ir.nodes[0].model_copy(update={"depends_on": ("ghost",)}),),
        )


@pytest.mark.parametrize(
    ("kind", "inputs", "dag_kind"),
    [
        ("clip", {"src": "@sources.a"}, "trim"),
        ("resize", {"src": "@sources.a"}, "resize"),
        ("crop", {"src": "@sources.a"}, "crop"),
        ("text", {"src": "@sources.a"}, "add_text"),
        ("subtitles", {"srcs": ["@sources.a", "@sources.b"]}, "burn_in"),
        ("merge", {"srcs": ["@sources.a", "@sources.b"]}, "merge"),
        (
            "composite",
            {"layers": [{"id": "base", "type": "video", "src": "@sources.a"}]},
            "composite_layers",
        ),
    ],
)
def test_every_closed_kind_compiles_to_expected_dag_kind(kind, inputs, dag_kind):
    ir = TimelineIR(
        sources={
            "a": IRSource(path="a.mp4"),
            "b": IRSource(path="b.srt"),
        },
        nodes=(
            IRNode(
                id="node",
                kind=kind,
                inputs=inputs,
                output="@outputs.out",
            ),
        ),
        outputs={"out": IROutput(path="out.mp4")},
    )
    assert compile_ir_to_dag(ir).nodes[0].kind == dag_kind


def test_input_shapes_fail_at_ir_boundary():
    with pytest.raises(MCPVideoError):
        IRNode(id="bad", kind="merge", inputs={"srcs": "@sources.a"})
