from __future__ import annotations

import json
import subprocess
import sys

import pytest

from mcp_video.client import Client
from mcp_video.errors import MCPVideoError


SHA = "sha256:" + "a" * 64
MODEL_SHA = "sha256:" + "b" * 64


def _timeline_request() -> dict[str, object]:
    provenance = {
        "analyzer_id": "fixture.surface",
        "analyzer_version": "1",
        "model_id": "fixture-local",
        "model_sha256": MODEL_SHA,
        "determinism_scope": "fixture inputs",
    }
    return {
        "source": {"content_sha256": SHA, "duration_seconds": 3.0},
        "words": [
            {
                "start_seconds": 1.0,
                "end_seconds": 1.2,
                "confidence": 0.99,
                "provenance": provenance,
                "text": "um",
                "disfluency": "filler",
            }
        ],
        "shots": [
            {
                "start_seconds": 0.0,
                "end_seconds": 3.0,
                "confidence": 1.0,
                "provenance": provenance,
                "ordinal": 0,
            }
        ],
    }


def test_python_surface_round_trips_timeline_query_and_approved_edit() -> None:
    client = Client()
    timeline = client.semantic_timeline(_timeline_request())
    query = client.semantic_query({"artifact": timeline, "text": "um"})
    unapproved = client.timeline_edit_plan({"timeline": timeline, "behavior": "filler"})
    edit_id = unapproved["edl"]["edits"][0]["edit_id"]
    approved = client.timeline_edit_plan({"timeline": timeline, "behavior": "filler", "selected_edit_ids": [edit_id]})

    assert query["results"][0]["source_text"] == "um"
    assert "approval" not in unapproved
    assert approved["approval"]["selected_edit_ids"] == [edit_id]
    assert approved["verification"]["passed"] is True


def test_python_surface_builds_visual_restoration_composition_and_remote_plans() -> None:
    client = Client()
    visual = client.visual_transform_plan(
        {
            "operation": "analysis",
            "payload": {
                "source": {"sha256": SHA, "width": 1920, "height": 1080, "duration_seconds": 1.0},
                "frames": [
                    {
                        "timestamp_seconds": 0.0,
                        "subjects": [
                            {
                                "subject_id": "subject-1",
                                "box": {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.5},
                                "confidence": 0.9,
                            }
                        ],
                        "camera_motion": {
                            "dx": 0.0,
                            "dy": 0.0,
                            "rotation_degrees": 0.0,
                            "confidence": 0.9,
                        },
                    }
                ],
                "primary_subject_id": "subject-1",
            },
        }
    )
    restoration = client.restoration_plan(
        {
            "feature": "styled_captions",
            "source_sha256": SHA,
            "requested_executor_id": "local.styled_captions",
        }
    )
    composition = client.composition_plan(
        {"operation": "manifest", "payload": {"project_id": "project:surface", "assets": []}}
    )
    remote = client.remote_egress_plan(
        {
            "files": [
                {
                    "path": "inputs/source.mp4",
                    "sha256": SHA,
                    "size_bytes": 1,
                    "media_type": "video/mp4",
                }
            ],
            "metadata": {"purpose": "explicit render"},
            "provider": "fake-render",
            "region_known": True,
            "region": "us-west-2",
            "retention": {"mode": "delete_after_download", "maximum_days": 1},
            "estimated_cost": {"amount": "1.25", "currency": "USD"},
        }
    )

    assert visual["plan_kind"] == "visual_analysis"
    assert restoration["feature"] == "styled_captions"
    assert composition["receipt_kind"] == "creative_project_manifest"
    assert remote["manifest_sha256"].startswith("sha256:")


def test_cli_surface_reads_bounded_json_request_and_emits_json(tmp_path) -> None:
    request = tmp_path / "semantic-request.json"
    request.write_text(json.dumps(_timeline_request()), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--format", "json", "semantic-timeline", str(request)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["artifact_kind"] == "semantic_timeline"


def test_public_surface_translates_invalid_contracts_and_does_not_echo_paths(tmp_path) -> None:
    client = Client()
    with pytest.raises(MCPVideoError) as invalid:
        client.restoration_plan({"feature": "styled_captions"})
    assert invalid.value.code == "invalid_post_rescue_request"

    missing = tmp_path / "private" / "request.json"
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--format", "json", "semantic-timeline", str(missing)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert str(missing) not in completed.stderr
    assert json.loads(completed.stderr)["error"]["code"] == "invalid_post_rescue_request"


def test_unsupported_operation_fails_closed() -> None:
    with pytest.raises(MCPVideoError, match="Unsupported operation"):
        Client().visual_transform_plan({"operation": "render", "payload": {}})


def test_client_introspection_declares_post_rescue_methods_as_planning_reports() -> None:
    contract = Client().inspect("semantic_timeline")

    assert contract["category"] == "planning"
    assert contract["return_type"] == "dict"
    assert contract["parameters"] == {"request": "Request"}
