"""Cutfile — text-first project format (TE.11).

Validate/load live here. Render lowers a validated cutfile to the workflow
engine via :func:`kinocut.te.cutfile_render.render_cutfile` (allowlisted ops
only; see workflow OP_ADAPTERS).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError


@dataclass
class Cutfile:
    name: str
    version: int = 1
    sources: list[dict[str, Any]] = field(default_factory=list)
    ops: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_kind": "cutfile", **asdict(self)}


def load_cutfile(path: str) -> Cutfile:
    """Load a minimal YAML-ish or JSON Cutfile (JSON preferred for v1)."""
    p = Path(path)
    if not p.is_file():
        raise InputFileError(str(p), "cutfile not found")
    text = p.read_text(encoding="utf-8")
    data = _parse_simple(text)
    return validate_cutfile(data)


def validate_cutfile(data: dict[str, Any]) -> Cutfile:
    if not isinstance(data, dict):
        raise MCPVideoError(
            "cutfile root must be an object",
            error_type="validation_error",
            code="invalid_cutfile",
        )
    name = data.get("name")
    if not name:
        raise MCPVideoError(
            "cutfile.name is required",
            error_type="validation_error",
            code="cutfile_name_required",
        )
    version = int(data.get("version") or 1)
    if version != 1:
        raise MCPVideoError(
            f"unsupported cutfile version {version}",
            error_type="validation_error",
            code="cutfile_version",
        )
    sources = list(data.get("sources") or [])
    ops = list(data.get("ops") or [])
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op:
            raise MCPVideoError(
                f"ops[{i}] must be object with op key",
                error_type="validation_error",
                code="invalid_cutfile_op",
            )
    return Cutfile(name=str(name), version=version, sources=sources, ops=ops)


def _parse_simple(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{"):
        import json

        return json.loads(text)
    # Minimal YAML subset: key: value and empty lists only for scaffold files.
    data: dict[str, Any] = {"sources": [], "ops": []}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key in {"sources", "ops"} and (val == "[]" or val == ""):
            data[key] = []
        elif key == "version":
            data[key] = int(val or 1)
        else:
            data[key] = val
    return data
