"""OTIO JSON bridge over the existing Timeline IR package (P4.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError
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
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {
        "artifact_kind": "otio_export",
        "path": str(path.resolve()),
        "clip_count": len(clips),
        "ir_name": ir.name,
    }


def import_otio_json(path: str) -> dict[str, Any]:
    """Import OTIO JSON that embeds kinocut_ir, or rebuild a minimal IR."""
    p = Path(path)
    if not p.is_file():
        raise InputFileError(str(p), "otio json not found")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPVideoError(f"invalid otio json: {exc}", error_type="validation_error", code="invalid_otio") from exc
    meta = doc.get("metadata") or {}
    if isinstance(meta.get("kinocut_ir"), dict):
        ir = parse_timeline_ir(meta["kinocut_ir"])
        return {
            "artifact_kind": "timeline_ir",
            **ir.model_dump(mode="json"),
            "identity": None,
        }
    # Minimal rebuild from clip names
    children = []
    tracks = doc.get("tracks") or {}
    for track in tracks.get("children") or []:
        children.extend(track.get("children") or [])
    if not children:
        raise MCPVideoError("otio has no clips and no kinocut_ir", error_type="validation_error", code="empty_otio")
    # Cannot invent confined sources — require embedded IR for full fidelity.
    raise MCPVideoError(
        "otio import requires metadata.kinocut_ir for confined sources",
        error_type="validation_error",
        code="otio_needs_kinocut_ir",
    )
