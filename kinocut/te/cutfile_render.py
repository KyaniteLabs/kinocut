"""Cutfile render — lower a validated Cutfile to the workflow engine (TE.11).

Thin path only: schema-valid cutfile ops that map to workflow OP_ADAPTERS are
compiled into a job-spec and executed via ``render_workflow``. Unsupported ops
fail closed. No parallel FFmpeg stack is introduced here.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.te.cutfile import Cutfile, load_cutfile
from kinocut.workflow.ops import OP_ADAPTERS

_RESERVED_OP_KEYS = frozenset({"op", "id", "src", "srcs", "output", "params"})
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _cutfile_error(message: str, code: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _normalize_sources(sources: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map cutfile sources list → workflow sources dict (id → {path})."""
    if not sources:
        raise _cutfile_error("cutfile.sources must be non-empty to render", "cutfile_sources_required")
    out: dict[str, dict[str, str]] = {}
    for i, raw in enumerate(sources):
        if not isinstance(raw, dict):
            raise _cutfile_error(f"sources[{i}] must be an object", "invalid_cutfile_source")
        sid = raw.get("id") or raw.get("name")
        path = raw.get("path")
        if not sid or not isinstance(sid, str):
            raise _cutfile_error(f"sources[{i}].id is required", "cutfile_source_id")
        if not _ID_RE.match(sid):
            raise _cutfile_error(f"sources[{i}].id is invalid: {sid!r}", "cutfile_source_id")
        if not path or not isinstance(path, str):
            raise _cutfile_error(f"sources[{i}].path is required", "cutfile_source_path")
        if sid in out:
            raise _cutfile_error(f"duplicate source id {sid!r}", "cutfile_source_duplicate")
        out[sid] = {"path": path}
    return out


def _op_params(op: dict[str, Any]) -> dict[str, Any]:
    if isinstance(op.get("params"), dict):
        return dict(op["params"])
    return {k: v for k, v in op.items() if k not in _RESERVED_OP_KEYS}


def _resolve_token(
    token: str,
    *,
    source_ids: set[str],
    step_outputs: dict[str, str],
) -> str:
    """Resolve a cutfile ref token to a workflow @ref."""
    if token.startswith("@sources.") or token.startswith("@work/") or token.startswith("@outputs."):
        return token
    if token in source_ids:
        return f"@sources.{token}"
    if token in step_outputs:
        return step_outputs[token]
    raise _cutfile_error(f"unknown cutfile ref {token!r}", "cutfile_unknown_ref")


def _default_src(
    *,
    source_ids: list[str],
    last_ref: str | None,
) -> str:
    if last_ref is not None:
        return last_ref
    if not source_ids:
        raise _cutfile_error("no sources available for default src", "cutfile_sources_required")
    return f"@sources.{source_ids[0]}"


def _step_id(op: dict[str, Any], index: int, used: set[str]) -> str:
    raw = op.get("id")
    if raw is None:
        candidate = f"step_{index + 1}"
    elif isinstance(raw, str) and _ID_RE.match(raw):
        candidate = raw
    else:
        raise _cutfile_error(f"ops[{index}].id is invalid", "invalid_cutfile_op")
    if candidate in used:
        raise _cutfile_error(f"duplicate op id {candidate!r}", "cutfile_op_duplicate")
    used.add(candidate)
    return candidate


def _validate_output_relpath(output_relpath: str) -> None:
    if not output_relpath or not isinstance(output_relpath, str):
        raise _cutfile_error("output_relpath must be a non-empty string", "cutfile_output_invalid")
    if output_relpath.startswith("/") or ".." in Path(output_relpath).parts:
        raise _cutfile_error(
            "output_relpath must be workspace-relative without '..'",
            "cutfile_output_invalid",
        )


def _bind_inputs(
    op: dict[str, Any],
    *,
    index: int,
    op_name: str,
    multi_input: bool,
    source_ids: list[str],
    source_id_set: set[str],
    step_outputs: dict[str, str],
    last_ref: str | None,
) -> dict[str, Any]:
    if multi_input:
        raw_srcs = op.get("srcs")
        if not isinstance(raw_srcs, list) or not raw_srcs:
            raise _cutfile_error(
                f"ops[{index}] ({op_name}) requires non-empty srcs list",
                "cutfile_srcs_required",
            )
        return {
            "srcs": [
                _resolve_token(str(t), source_ids=source_id_set, step_outputs=step_outputs) for t in raw_srcs
            ]
        }
    raw_src = op.get("src")
    if raw_src is None:
        ref = _default_src(source_ids=source_ids, last_ref=last_ref)
    else:
        ref = _resolve_token(str(raw_src), source_ids=source_id_set, step_outputs=step_outputs)
    return {"src": ref}


def _compile_ops(
    ops: list[dict[str, Any]],
    *,
    source_ids: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Lower cutfile ops to workflow steps; return (steps, last_media_index)."""
    source_id_set = set(source_ids)
    steps: list[dict[str, Any]] = []
    step_outputs: dict[str, str] = {}
    used_ids: set[str] = set()
    last_ref: str | None = None
    last_media_step_index: int | None = None

    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise _cutfile_error(f"ops[{i}] must be an object", "invalid_cutfile_op")
        op_name = op.get("op")
        if not isinstance(op_name, str) or op_name not in OP_ADAPTERS:
            raise _cutfile_error(
                f"ops[{i}] unsupported op {op_name!r}; allowlist={sorted(OP_ADAPTERS)}",
                "cutfile_unsupported_op",
            )
        # Cutfile v1 only binds src / srcs — multi-layer adapters need a different shape.
        if op_name in {"composite_layers"}:
            raise _cutfile_error(
                f"ops[{i}] op {op_name!r} is not supported in cutfile v1 "
                "(requires layers binding; use workflow job-spec directly)",
                "cutfile_op_shape",
            )
        sid = _step_id(op, i, used_ids)
        adapter = OP_ADAPTERS[op_name]
        step: dict[str, Any] = {
            "id": sid,
            "op": op_name,
            "params": _op_params(op),
            "inputs": _bind_inputs(
                op,
                index=i,
                op_name=op_name,
                multi_input=adapter.multi_input,
                source_ids=source_ids,
                source_id_set=source_id_set,
                step_outputs=step_outputs,
                last_ref=last_ref,
            ),
        }
        if adapter.has_output:
            work_ref = f"@work/{sid}.mp4"
            step["output"] = work_ref
            step_outputs[sid] = work_ref
            last_ref = work_ref
            last_media_step_index = len(steps)
        steps.append(step)

    if last_media_step_index is None:
        raise _cutfile_error(
            "cutfile has no media-producing ops (probe-only is not a render)",
            "cutfile_no_media_ops",
        )
    return steps, last_media_step_index


def compile_cutfile_to_workflow(
    cutfile: Cutfile,
    *,
    output_relpath: str = "out/final.mp4",
) -> dict[str, Any]:
    """Compile a validated Cutfile into a workflow job-spec dict (schema_version 1).

    Linear chaining: single-input ops without ``src`` use the previous media
    output (or the first source). ``merge`` requires ``srcs``. Only ops present
    in the workflow OP_ADAPTERS allowlist are accepted.
    """
    if not cutfile.ops:
        raise _cutfile_error("cutfile.ops must be non-empty to render", "cutfile_ops_required")
    _validate_output_relpath(output_relpath)

    sources = _normalize_sources(cutfile.sources)
    steps, last_media_i = _compile_ops(cutfile.ops, source_ids=list(sources.keys()))
    steps[last_media_i]["output"] = "@outputs.master"

    return {
        "schema_version": 1,
        "name": cutfile.name,
        "sources": sources,
        "steps": steps,
        "outputs": {"master": {"path": output_relpath}},
    }


def render_cutfile(
    path: str,
    *,
    output_path: str | None = None,
    save_receipt: str | None = None,
    keep_intermediates: bool = False,
) -> dict[str, Any]:
    """Load a cutfile, compile to workflow, and render via the workflow engine.

    The cutfile's parent directory is the workspace root (sources and outputs
    are relative to it). Returns a dict with cutfile identity plus the workflow
    receipt fields.
    """
    from kinocut.workflow import render_workflow

    cutfile_path = Path(path).expanduser().resolve()
    cf = load_cutfile(str(cutfile_path))
    workspace = cutfile_path.parent
    rel_out = output_path or f"out/{_safe_slug(cf.name)}.mp4"
    if Path(rel_out).is_absolute():
        try:
            rel_out = str(Path(rel_out).resolve().relative_to(workspace))
        except ValueError as exc:
            raise _cutfile_error(
                "output_path must be inside the cutfile workspace",
                "cutfile_output_invalid",
            ) from exc

    (workspace / "out").mkdir(parents=True, exist_ok=True)
    spec = compile_cutfile_to_workflow(cf, output_relpath=rel_out)
    spec_fd, spec_name = tempfile.mkstemp(
        prefix=f".cutfile_workflow_{_safe_slug(cf.name)}_",
        suffix=".json",
        dir=str(workspace),
    )
    os.close(spec_fd)
    spec_path = Path(spec_name)
    try:
        spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        receipt_path = save_receipt
        if receipt_path is None:
            receipts_dir = workspace / "receipts"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = str(receipts_dir / f"{_safe_slug(cf.name)}.receipt.json")

        receipt = render_workflow(
            str(spec_path),
            save_receipt=receipt_path,
            keep_intermediates=keep_intermediates,
        )
    finally:
        if not keep_intermediates:
            with contextlib.suppress(OSError):
                spec_path.unlink(missing_ok=True)

    final = workspace / rel_out
    return {
        "artifact_kind": "cutfile_render",
        "cutfile": str(cutfile_path),
        "name": cf.name,
        "version": cf.version,
        "output_path": str(final) if final.is_file() else rel_out,
        "workflow_spec": str(spec_path) if keep_intermediates and spec_path.is_file() else None,
        "receipt_path": receipt_path,
        "workflow": receipt,
    }


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()) or "cutfile"
    return slug[:80]
