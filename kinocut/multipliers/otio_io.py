"""OTIO JSON bridge over the existing Timeline IR package (P4.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_artifact_path, _validate_input_path
from kinocut.timeline_ir import compile_ir_to_dag, parse_timeline_ir


def export_otio_json(timeline: dict[str, Any], output_path: str) -> dict[str, Any]:
    """Export a Timeline IR dict to simplified OTIO JSON + compile proof."""
    ir = parse_timeline_ir(timeline)
    dag = compile_ir_to_dag(ir)
    clips = []
    for node in ir.nodes:
        clips.append(
            {
                "OTIO_SCHEMA": "Clip.1",
                "name": node.id,
                "metadata": {
                    "kinocut_kind": node.kind,
                    "params": node.params,
                    "depends_on": list(node.depends_on),
                },
            }
        )
    doc = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": ir.name,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "V1",
                    "kind": "Video",
                    "children": clips,
                }
            ],
        },
        "metadata": {
            "kinocut_ir": ir.model_dump(mode="json"),
            "kinocut_dag_nodes": len(dag.nodes) if hasattr(dag, "nodes") else None,
        },
    }
    path = Path(_validate_artifact_path(output_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact_kind": "otio_export",
        "path": str(path.resolve()),
        "clip_count": len(clips),
        "ir_name": ir.name,
    }


def _media_path_from_clip(clip: dict[str, Any]) -> str | None:
    """Extract a local filesystem path from a foreign OTIO Clip media reference."""
    if not isinstance(clip, dict):
        return None
    # Common shapes: media_reference.target_url, media.media_reference.target_url
    for key in ("media_reference", "media"):
        ref = clip.get(key)
        if isinstance(ref, dict):
            nested = ref.get("media_reference") if key == "media" else ref
            if isinstance(nested, dict):
                url = nested.get("target_url") or nested.get("target_url_or_path")
                if isinstance(url, str) and url.strip():
                    return _url_to_local_path(url.strip())
            url = ref.get("target_url") if isinstance(ref, dict) else None
            if isinstance(url, str) and url.strip():
                return _url_to_local_path(url.strip())
    meta = clip.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("source", "path", "media_path"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _url_to_local_path(url: str) -> str | None:
    if url.startswith("file://"):
        parsed = urlparse(url)
        return unquote(parsed.path)
    if "://" in url and not url.startswith("file:"):
        # Remote URLs are never auto-fetched — fail closed at import time.
        return None
    return url


def _collect_track_children(doc: dict[str, Any]) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    tracks = doc.get("tracks")
    if isinstance(tracks, dict):
        for track in tracks.get("children") or []:
            if isinstance(track, dict):
                for child in track.get("children") or []:
                    if isinstance(child, dict):
                        children.append(child)
    elif isinstance(tracks, list):
        for track in tracks:
            if isinstance(track, dict):
                for child in track.get("children") or []:
                    if isinstance(child, dict):
                        children.append(child)
    return children


def _is_confined_relpath(value: str) -> bool:
    """Match Timeline IR path rules: relative, no traversal, no absolute."""
    if not value or "\\" in value or "\x00" in value or value.startswith("/"):
        return False
    return not any(part in {"", ".", ".."} for part in value.split("/"))


def _resolve_foreign_clips(children: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate local media paths for foreign OTIO clips."""
    resolved: list[dict[str, str]] = []
    for idx, clip in enumerate(children):
        media_path = _media_path_from_clip(clip)
        if not media_path:
            raise MCPVideoError(
                f"foreign otio clip[{idx}] has no local media_reference path "
                "(remote URLs are not fetched; embed metadata.kinocut_ir or file:// paths)",
                error_type="validation_error",
                code="otio_foreign_no_local_media",
            )
        try:
            validated = _validate_input_path(media_path)
        except Exception as exc:
            raise MCPVideoError(
                f"foreign otio clip[{idx}] media path rejected: {media_path}",
                error_type="validation_error",
                code="otio_foreign_media_invalid",
            ) from exc
        node_id = str(clip.get("name") or f"c{idx + 1}")
        resolved.append({"id": node_id, "source": validated, "raw": media_path})
    return resolved


def _timeline_ir_from_confined(resolved: list[dict[str, str]], name: str) -> dict[str, Any]:
    """Build Timeline IR when all foreign sources are confined relative paths."""
    sources: dict[str, dict[str, str]] = {}
    nodes: list[dict[str, Any]] = []
    for idx, clip in enumerate(resolved):
        src_id = f"s{idx + 1}"
        sources[src_id] = {"path": clip["raw"]}
        nodes.append(
            {
                "id": clip["id"],
                "kind": "clip",
                "depends_on": [],
                "inputs": {"src": f"@sources.{src_id}"},
                "params": {
                    "start": {"numerator": 0, "denominator": 1},
                    "duration": {"numerator": 1, "denominator": 1},
                },
                "output": f"@outputs.clip_{idx + 1}",
            }
        )
    timeline = {
        "ir_schema_version": 1,
        "name": name,
        "timebase": {"numerator": 1, "denominator": 30},
        "sources": sources,
        "nodes": nodes,
        "outputs": {"final": {"path": "out/final.mp4"}},
    }
    ir = parse_timeline_ir(timeline)
    return {
        "artifact_kind": "timeline_ir",
        **ir.model_dump(mode="json"),
        "identity": None,
        "import_mode": "foreign_local_media_confined",
        "clip_count": len(nodes),
    }


def _import_foreign_otio(doc: dict[str, Any], path: Path) -> dict[str, Any]:
    """Import foreign OTIO JSON when clips resolve to local media paths.

    Absolute/local validated paths → ``foreign_otio_import`` + sequence shortcut.
    Confined relative paths → full ``timeline_ir``.
    """
    children = _collect_track_children(doc)
    if not children:
        raise MCPVideoError(
            "otio has no clips and no kinocut_ir",
            error_type="validation_error",
            code="empty_otio",
        )
    resolved = _resolve_foreign_clips(children)
    name = str(doc.get("name") or path.stem or "foreign_otio")
    if all(_is_confined_relpath(c["raw"]) for c in resolved):
        return _timeline_ir_from_confined(resolved, name)
    return {
        "artifact_kind": "foreign_otio_import",
        "import_mode": "foreign_local_media",
        "name": name,
        "clip_count": len(resolved),
        "clips": resolved,
        "sequence_shortcut": {
            "clips": [c["source"] for c in resolved],
            "transitions": [],
            "transition_duration": 1.0,
        },
        "next_action": "video_edit_sequence_shortcut_or_merge",
    }


def import_otio_json(path: str) -> dict[str, Any]:
    """Import OTIO JSON that embeds kinocut_ir, or foreign clips with local media.

    Priority:
    1. ``metadata.kinocut_ir`` — full-fidelity Kinocut Timeline IR
    2. Foreign OTIO clips whose ``media_reference.target_url`` resolves to a
       confined local path (``file://`` or bare path). Remote URLs are rejected.
    """
    p = Path(_validate_input_path(path))
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPVideoError(f"invalid otio json: {exc}", error_type="validation_error", code="invalid_otio") from exc
    if not isinstance(doc, dict):
        raise MCPVideoError("otio root must be an object", error_type="validation_error", code="invalid_otio")
    meta = doc.get("metadata") or {}
    if isinstance(meta, dict) and isinstance(meta.get("kinocut_ir"), dict):
        ir = parse_timeline_ir(meta["kinocut_ir"])
        return {
            "artifact_kind": "timeline_ir",
            **ir.model_dump(mode="json"),
            "identity": None,
            "import_mode": "kinocut_ir",
        }
    return _import_foreign_otio(doc, p)
