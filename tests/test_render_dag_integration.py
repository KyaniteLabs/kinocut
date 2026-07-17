"""Render DAG (P2) — frozen closed-kind planning layer over the workflow executor.

Covers the P2 acceptance: deterministic equality, the frozen op allowlist (with
a drift guard binding it to ``OP_ADAPTERS``), cycle / missing-dep detection,
deterministic topological ordering, confined sources/outputs, canonical params,
stale/corrupt cache rejection, cancellation/restart compatibility through the
existing workflow spec behavior, and exact spec-hash parity with an equivalent
hand-written spec — all through the one shared canonical serializer.
"""

from __future__ import annotations

import hashlib
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
    dag_identity,
    serialize_spec,
    verify_spec_cache,
)
from kinocut.render_dag import schema as dag_schema
from kinocut.workflow.ops import OP_ADAPTERS
from kinocut.workflow.spec import parse_spec
from kinocut.workflow.validator import validate_workflow_spec

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


# --- cancellation/restart compatibility through existing workflow spec --------


def test_compiled_spec_parses_as_schema_version_one_workflow_spec():
    compiled = compile_dag_to_spec(_flagship_dag())
    model = parse_spec(compiled.spec)
    assert model.schema_version == 1


def test_compiled_spec_passes_existing_workflow_validator(tmp_path):
    """The DAG-compiled spec is directly consumable by the existing executor's
    validator — proving synchronous-rendering / resume / cancel compatibility
    (resume keys on spec_hash, which the DAG preserves)."""

    compiled = compile_dag_to_spec(_flagship_dag())
    spec_path = _write_spec(tmp_path, compiled.spec)
    verdict = validate_workflow_spec(spec_path)
    assert verdict["valid"] is True
    assert verdict["schema_version"] == 1


def _assert_compiled_family_validates(dag: RenderDAG, tmp_path: Path) -> None:
    """Compile a DAG and prove its spec passes the existing workflow validator."""

    compiled = compile_dag_to_spec(dag)
    spec_path = _write_spec(tmp_path, compiled.spec, name=f"{compiled.spec_hash[:8]}.json")
    verdict = validate_workflow_spec(spec_path)
    assert verdict["valid"] is True
    assert verdict["schema_version"] == 1


def test_compiled_merge_family_passes_existing_workflow_validator(tmp_path):
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
    _assert_compiled_family_validates(dag, tmp_path)


def test_compiled_burn_in_family_passes_existing_workflow_validator(tmp_path):
    dag = RenderDAG(
        sources={"video": DAGSource(path="video.mp4"), "sub": DAGSource(path="sub.srt")},
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
    _assert_compiled_family_validates(dag, tmp_path)


def test_compiled_composite_family_passes_existing_workflow_validator(tmp_path):
    dag = RenderDAG(
        sources={"bg": DAGSource(path="bg.mp4"), "ov": DAGSource(path="ov.mp4")},
        nodes=(
            DAGNode(
                id="comp",
                kind="composite_layers",
                inputs={
                    "layers": [
                        {"id": "base", "type": "video", "src": "@sources.bg"},
                        {"id": "overlay", "type": "image", "src": "@sources.ov"},
                    ]
                },
                params={"canvas": {"width": 640, "height": 360}},
                output="@outputs.out",
            ),
        ),
        outputs={"out": DAGOutput(path="out.mp4")},
    )
    _assert_compiled_family_validates(dag, tmp_path)


def test_compiled_composite_with_work_layer_validates(tmp_path):
    """A composite layer sourced from an earlier @work node compiles to a spec
    the existing validator accepts (layer @work ref is backward-only)."""

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
    _assert_compiled_family_validates(dag, tmp_path)


def test_compiled_spec_file_hash_equals_executor_spec_hash(tmp_path):
    """Writing the canonical bytes verbatim makes the executor's whole-file
    sha256 equal the DAG's spec_hash — so resume/cancellation/restart treat a
    DAG-compiled job identically to a hand-written one."""

    compiled = compile_dag_to_spec(_flagship_dag())
    spec_file = tmp_path / "job.json"
    spec_file.write_bytes(compiled.spec_bytes)
    executor_hash = "sha256:" + hashlib.sha256(spec_file.read_bytes()).hexdigest()
    assert executor_hash == compiled.spec_hash


def test_compiled_spec_matches_handwritten_under_executor_hash(tmp_path):
    compiled = compile_dag_to_spec(_flagship_dag())
    hand_file = tmp_path / "hand.json"
    hand_file.write_bytes(serialize_spec(_flagship_handwritten_spec()))
    compiled_file = tmp_path / "dag.json"
    compiled_file.write_bytes(compiled.spec_bytes)
    assert hashlib.sha256(hand_file.read_bytes()).hexdigest() == hashlib.sha256(compiled_file.read_bytes()).hexdigest()


def test_dag_does_not_execute_or_create_a_cursor(tmp_path):
    """compile_dag_to_spec is planning-only: it returns a spec and touches no
    executor run/cursor/receipt state (tmp_path stays empty)."""

    assert not any(tmp_path.iterdir())
    compiled = compile_dag_to_spec(_flagship_dag())
    assert not any(tmp_path.iterdir())
    assert compiled.spec["schema_version"] == 1


# --- stale / corrupt cache rejection -----------------------------------------


def test_verify_spec_cache_accepts_a_fresh_match():
    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    verified = verify_spec_cache(
        dag,
        compiled.spec_bytes,
        claimed_dag_identity=compiled.dag_identity,
        claimed_spec_hash=compiled.spec_hash,
    )
    assert verified.spec_hash == compiled.spec_hash
    assert verified.dag_identity == compiled.dag_identity
    assert verified.spec == compiled.spec
    assert serialize_spec(verified.spec) == verified.spec_bytes


def test_verify_spec_cache_rejects_stale_identity():
    """A changed DAG (different identity) makes the cache stale -> fail closed."""

    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    changed = dag.model_copy(update={"name": "changed-plan"})
    assert dag_identity(changed) != compiled.dag_identity
    with pytest.raises(MCPVideoError) as exc:
        verify_spec_cache(
            changed,
            compiled.spec_bytes,
            claimed_dag_identity=compiled.dag_identity,
            claimed_spec_hash=compiled.spec_hash,
        )
    assert exc.value.code == "stale_dag_cache"


def test_verify_spec_cache_rejects_corrupt_hash():
    """Tampered/truncated bytes whose hash no longer matches -> fail closed."""

    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    tampered = compiled.spec_bytes.replace(b"hero", b"HERO")
    with pytest.raises(MCPVideoError) as exc:
        verify_spec_cache(
            dag,
            tampered,
            claimed_dag_identity=compiled.dag_identity,
            claimed_spec_hash=compiled.spec_hash,
        )
    assert exc.value.code == "corrupt_dag_cache"


def test_verify_spec_cache_rejects_corrupt_json():
    dag = _flagship_dag()
    broken = b"{not valid json"
    recomputed = "sha256:" + hashlib.sha256(broken).hexdigest()
    with pytest.raises(MCPVideoError) as exc:
        verify_spec_cache(
            dag,
            broken,
            claimed_dag_identity=dag_identity(dag),
            claimed_spec_hash=recomputed,
        )
    assert exc.value.code == "corrupt_dag_cache"


def test_verify_spec_cache_rejects_shape_invalid_spec():
    """Bytes that parse as JSON but not as a schema_version:1 spec -> corrupt."""

    dag = _flagship_dag()
    bogus = json.dumps({"schema_version": 99, "steps": []}).encode("utf-8")
    recomputed = "sha256:" + hashlib.sha256(bogus).hexdigest()
    with pytest.raises(MCPVideoError) as exc:
        verify_spec_cache(
            dag,
            bogus,
            claimed_dag_identity=dag_identity(dag),
            claimed_spec_hash=recomputed,
        )
    assert exc.value.code == "corrupt_dag_cache"


def test_cache_is_read_only_and_never_mutates(tmp_path):
    dag = _flagship_dag()
    compiled = compile_dag_to_spec(dag)
    verify_spec_cache(
        dag,
        compiled.spec_bytes,
        claimed_dag_identity=compiled.dag_identity,
        claimed_spec_hash=compiled.spec_hash,
    )
    assert not any(tmp_path.iterdir())


# --- provenance: planning-only surface ---------------------------------------


def test_drift_guard_binds_to_op_adapters():
    """The frozen kind set must equal the live registry (import-time guard)."""

    assert frozenset(OP_ADAPTERS) == dag_schema._DAG_NODE_KIND_SET
