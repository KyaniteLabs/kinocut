from __future__ import annotations

import mcp_video.semantic as semantic
from mcp_video.semantic.edl import EditApproval, TimelineDiff
from mcp_video.semantic.index import SemanticIndex
from mcp_video.semantic.models import SemanticTimeline


SHA = "sha256:" + "7" * 64
MODEL_SHA = "sha256:" + "8" * 64


def _timeline_payload() -> dict[str, object]:
    provenance = {
        "analyzer_id": "fixture.surface",
        "analyzer_version": "1",
        "model_id": "fixture",
        "model_sha256": MODEL_SHA,
        "determinism_scope": "fixture",
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


def test_package_exports_only_small_surface_ready_pure_api() -> None:
    assert semantic.__all__ == [
        "build_edl",
        "build_semantic_timeline",
        "generate_ordinary_cleanup_edits",
        "query_local_index",
        "verify_edl",
    ]


def test_surface_functions_accept_models_or_json_mappings_and_return_models() -> None:
    timeline = semantic.build_semantic_timeline(**_timeline_payload())
    index_response = semantic.query_local_index(timeline, text="um")
    edl = semantic.generate_ordinary_cleanup_edits(timeline.model_dump(mode="json"), behavior="filler")
    approval = EditApproval.create(edl=edl, selected_edit_ids=tuple(edit.edit_id for edit in edl.edits))
    diff = TimelineDiff.create(timeline=timeline, edl=edl, approval=approval)
    verification = semantic.verify_edl(
        timeline.model_dump(mode="json"),
        edl.model_dump(mode="json"),
        approval.model_dump(mode="json"),
        diff.model_dump(mode="json"),
    )
    rebuilt = semantic.build_edl(timeline, edits=tuple(edit.model_dump(mode="json") for edit in edl.edits))

    assert isinstance(timeline, SemanticTimeline)
    assert isinstance(index_response.index, SemanticIndex)
    assert index_response.results[0].source_text == "um"
    assert rebuilt.edl_sha256 == edl.edl_sha256
    assert verification.passed
