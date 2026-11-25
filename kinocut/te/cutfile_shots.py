"""Execute a Cutfile whose sole operation is a cached shot plan."""

from pathlib import Path
from typing import Any

from kinocut.publication import durable_receipt_ownership
from kinocut.shot_cache import ShotSpec, render_shot_plan
from kinocut.workflow.planner import _confine_artifact_path
from kinocut.workflow.receipt import _write_receipt

from .cutfile import Cutfile
from .cutfile_render import _cutfile_error, _normalize_sources, _safe_slug


def _local(workspace: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Expected a workspace-relative path")
    path = workspace / name
    _confine_artifact_path(str(path), workspace, "cached shot plan")
    return path


def _shot(raw: dict[str, Any], sources: dict[str, dict[str, str]], workspace: Path, trusted: bool) -> ShotSpec:
    if not isinstance(raw, dict):
        raise ValueError("Each shot must be an object")
    data = dict(raw)
    if "source_path" in data:
        raise ValueError("Reference a Cutfile source with src, not source_path")
    if "src" in data:
        source = data.pop("src")
        if not isinstance(source, str) or source not in sources:
            raise ValueError("Unknown cached shot source")
        data["source_path"] = _local(workspace, sources[source]["path"])
    if "command" in data and trusted is not True:
        raise _cutfile_error("External producers require --allow-external-producers", "cutfile_untrusted_producer")
    for key in ("command", "dependencies"):
        if key in data:
            value = data[key]
            if not isinstance(value, list) or not all(isinstance(arg, str) for arg in value):
                raise ValueError(f"{key} must be an array of strings")
            data[key] = tuple(value)
    return ShotSpec(**data)


def render_cached_cutfile(cf: Cutfile, path: Path, output: str, receipt: str | None, trusted: bool) -> dict[str, Any]:
    if len(cf.ops) != 1:
        raise _cutfile_error("cached_shots must be the sole Cutfile op", "invalid_cutfile_op")
    root = path.parent
    op = cf.ops[0]
    try:
        sources = _normalize_sources(cf.sources) if cf.sources else {}
        raw = op.get("shots")
        if not isinstance(raw, list) or not raw:
            raise ValueError("cached_shots requires a nonempty shots array")
        shots = [_shot(item, sources, root, trusted) for item in raw]
        cache = _local(root, op.get("cache_dir", "shot-cache"))
        final = _local(root, output)
    except (TypeError, ValueError) as exc:
        raise _cutfile_error(
            "Invalid cached shot plan: check the shot fields, source references and paths", "invalid_cutfile_op"
        ) from exc
    receipt = receipt or str(root / "receipts" / f"{_safe_slug(cf.name)}.receipt.json")
    _confine_artifact_path(receipt, root, "save_receipt")
    Path(receipt).parent.mkdir(parents=True, exist_ok=True)
    with durable_receipt_ownership(Path(receipt)):
        final.parent.mkdir(parents=True, exist_ok=True)
        result = render_shot_plan(shots, final, cache)
        envelope = {
            "artifact_kind": "cutfile_render",
            "cutfile": str(path),
            "name": cf.name,
            "version": cf.version,
            "output_path": str(final),
            "receipt_path": receipt,
            "shot_plan": result,
        }
        _write_receipt(envelope, receipt, root)
    return envelope
