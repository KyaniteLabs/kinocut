"""Boundary validation and discovery tests for Wave 3 governed operations."""

from __future__ import annotations

import subprocess
import sys

import pytest

from kinocut.errors import MCPVideoError

_MAX_AUTH_IDS = 64
_MAX_JSON_BYTES = 65_536


def test_wave3_lone_surrogates_are_typed_and_private_across_public_routes():
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.client import Client
    from kinocut.server_tools_aivideo import video_body_swap

    private = "private-\ud800-value"
    raising_calls = (
        lambda: run_wave3_operation(
            "body_swap",
            project_dir="unused",
            video_source="video",
            audio_source="audio",
            output_path=private,
            duration_policy=None,
            authorization_decision_ids=[],
        ),
        lambda: Client().body_swap("unused", "video", "audio", private),
    )
    for call in raising_calls:
        with pytest.raises(MCPVideoError) as exc:
            call()
        assert exc.value.code == "wave3_input_invalid"
        assert private not in str(exc.value)
    mcp_result = video_body_swap("unused", "video", "audio", private)
    assert mcp_result["success"] is False
    assert mcp_result["error"]["code"] == "wave3_input_invalid"
    assert private not in mcp_result["error"]["message"]


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    (
        ("verdict", {"project_dir": "unused", "verdict": []}),
        ("verdict", {"project_dir": "unused", "verdict": {"rationale": "x" * _MAX_JSON_BYTES}}),
        (
            "acceptance_eval",
            {
                "project_dir": "unused",
                "acceptance_spec_id": "sha256:" + "a" * 64,
                "verdict_ids": "not-a-list",
            },
        ),
        (
            "acceptance_eval",
            {
                "project_dir": "unused",
                "acceptance_spec_id": "sha256:" + "a" * 64,
                "verdict_ids": ["sha256:" + "a" * 64] * 65,
            },
        ),
        (
            "body_swap",
            {
                "project_dir": "unused",
                "video_source": "video",
                "audio_source": "audio",
                "output_path": "output",
                "duration_policy": None,
                "authorization_decision_ids": ["sha256:" + "a" * 64] * (_MAX_AUTH_IDS + 1),
            },
        ),
        (
            "body_swap",
            {
                "project_dir": "unused",
                "video_source": "video",
                "audio_source": "audio",
                "output_path": "output",
                "duration_policy": None,
                "authorization_decision_ids": "not-a-list",
            },
        ),
        (
            "salvage",
            {
                "project_dir": "unused",
                "source_asset_id": "sha256:" + "a" * 64,
                "recipe": "still_frame",
                "policy": {"padding": "x" * _MAX_JSON_BYTES},
                "acceptance_spec_id": "sha256:" + "a" * 64,
                "authorization_decision_ids": [],
            },
        ),
    ),
)
def test_wave3_boundary_rejects_malformed_or_unbounded_input(operation, kwargs):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    with pytest.raises(MCPVideoError) as exc:
        run_wave3_operation(operation, **kwargs)
    assert exc.value.error_type == "validation_error"
    assert exc.value.code in {
        "wave3_collection_invalid",
        "wave3_input_invalid",
        "wave3_input_too_large",
    }
    assert "unused" not in str(exc.value)


def test_client_search_tools_discovers_wave3_in_fresh_process():
    script = """
from kinocut import Client
names = {item['name'] for item in Client().search_tools('video_')['tools']}
required = {'video_verdict', 'video_acceptance_eval', 'video_body_swap', 'video_salvage'}
assert required <= names, sorted(required - names)
"""
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
