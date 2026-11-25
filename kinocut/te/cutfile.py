"""Cutfile — text-first project format (TE.11).

Validate/load live here. Render lowers a validated cutfile to the workflow
engine via :func:`kinocut.te.cutfile_render.render_cutfile` (allowlisted ops
only; see workflow OP_ADAPTERS).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path


@dataclass
class Cutfile:
    name: str
    version: int = 1
    sources: list[dict[str, Any]] = field(default_factory=list)
    ops: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_kind": "cutfile", **asdict(self)}

    def to_yaml(self) -> str:
        """Serialize this Cutfile cleanly to YAML."""
        import yaml

        payload = {
            "name": self.name,
            "version": self.version,
            "sources": self.sources,
            "ops": self.ops,
        }
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_cutfile(path: str) -> Cutfile:
    """Load a YAML or JSON Cutfile."""
    p = Path(path)
    if not p.is_file():
        raise InputFileError(str(p), "cutfile not found")
    validated = _validate_input_path(str(p))
    text = Path(validated).read_text(encoding="utf-8")
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
    if not name or not isinstance(name, str):
        raise MCPVideoError(
            "cutfile.name is required",
            error_type="validation_error",
            code="cutfile_name_required",
        )
    raw_version = data.get("version", 1)
    if raw_version is None:
        raw_version = 1
    if type(raw_version) is not int:
        raise MCPVideoError(
            "cutfile.version must be an integer",
            error_type="validation_error",
            code="cutfile_version",
        )
    version = raw_version
    if version != 1:
        raise MCPVideoError(
            f"unsupported cutfile version {version}",
            error_type="validation_error",
            code="cutfile_version",
        )
    raw_sources = data.get("sources")
    if raw_sources is None:
        sources: list[dict[str, Any]] = []
    elif isinstance(raw_sources, list):
        sources = list(raw_sources)
    else:
        raise MCPVideoError(
            "cutfile.sources must be a list",
            error_type="validation_error",
            code="invalid_cutfile",
        )
    raw_ops = data.get("ops")
    if raw_ops is None:
        ops: list[dict[str, Any]] = []
    elif isinstance(raw_ops, list):
        ops = list(raw_ops)
    else:
        raise MCPVideoError(
            "cutfile.ops must be a list",
            error_type="validation_error",
            code="invalid_cutfile",
        )
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op:
            raise MCPVideoError(
                f"ops[{i}] must be object with op key",
                error_type="validation_error",
                code="invalid_cutfile_op",
            )
    return Cutfile(name=str(name), version=version, sources=sources, ops=ops)


def _parse_simple(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise MCPVideoError(
            "cutfile is empty",
            error_type="validation_error",
            code="invalid_cutfile",
        )
    if stripped.startswith("{"):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise MCPVideoError(
                "invalid JSON cutfile",
                error_type="validation_error",
                code="invalid_cutfile",
            ) from exc
        if not isinstance(loaded, dict):
            raise MCPVideoError(
                "cutfile root must be an object",
                error_type="validation_error",
                code="invalid_cutfile",
            )
        return loaded
    try:
        import yaml
    except ImportError as exc:
        raise MCPVideoError(
            "PyYAML is required to parse YAML cutfiles; use JSON or install PyYAML",
            error_type="validation_error",
            code="yaml_parser_unavailable",
        ) from exc
    try:
        loaded = yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        raise MCPVideoError(
            "invalid YAML cutfile",
            error_type="validation_error",
            code="invalid_cutfile",
        ) from exc
    if not isinstance(loaded, dict):
        raise MCPVideoError(
            "cutfile root must be an object",
            error_type="validation_error",
            code="invalid_cutfile",
        )
    return loaded
