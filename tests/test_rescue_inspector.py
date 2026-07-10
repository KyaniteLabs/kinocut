"""Additive, read-only rescue artifact inspection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mcp_video.rescue.inspector import inspect_rescue


def _sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_inspector_tolerates_future_additive_fields(tmp_path):
    media = tmp_path / "master.mp4"
    media.write_bytes(b"media")
    receipt = {
        "schema_version": 1,
        "receipt_kind": "rescue",
        "tool": "video_rescue_render",
        "status": "completed",
        "source": {"path": "master.mp4", "sha256": _sha(media)},
        "approved_repair_ids": [],
        "applied_repair_ids": [],
        "skipped_repair_ids": [],
        "verification": [],
        "package": {"promoted": True, "artifacts": [{"kind": "master", "status": "available", "path": "master.mp4", "sha256": _sha(media)}]},
        "privacy": {"local_only": True, "network_used": False, "source_overwritten": False},
        "warnings": [],
        "cleanup": {},
        "resume": {},
        "future_field": {"kept": True},
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    inspected = inspect_rescue(str(path))

    assert inspected["kind"] == "rescue"
    assert inspected["integrity"]["all_present"] is True
    assert inspected["integrity"]["all_matching"] is True


def test_inspector_never_modifies_media(tmp_path):
    media = tmp_path / "master.mp4"
    media.write_bytes(b"media")
    before = _sha(media)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "receipt_kind": "rescue_plan",
        "tool": "video_rescue_plan",
        "status": "planned",
        "source": {"path": "master.mp4", "sha256": before},
        "safe_repairs": [], "recommendations": [], "unavailable_repairs": [], "blocked_repairs": [],
        "preview_artifacts": [], "warnings": [],
    }), encoding="utf-8")

    inspect_rescue(str(path))

    assert _sha(media) == before


def test_inspector_does_not_follow_package_path_outside_output(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    media = outside / "secret.mp4"
    media.write_bytes(b"secret")
    receipt = {
        "schema_version": 1,
        "receipt_kind": "rescue",
        "tool": "video_rescue_render",
        "status": "completed",
        "workspace_root": "..",
        "source": {"path": "outside/secret.mp4", "sha256": _sha(media)},
        "package": {
            "path": "../outside",
            "promoted": True,
            "artifacts": [{"kind": "master", "status": "available", "path": "secret.mp4", "sha256": _sha(media)}],
        },
    }
    path = output / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    inspected = inspect_rescue(str(path))

    package_artifact = inspected["integrity"]["artifacts"][1]
    assert package_artifact["present"] is False
