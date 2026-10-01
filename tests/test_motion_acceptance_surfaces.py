"""Operator parity preserves explicit unverified human attestation constraints."""

import argparse
import asyncio
from copy import deepcopy
import json

import pytest

from kinocut.aivideo.inspection.motion_acceptance import motion_review_items
from kinocut.cli.handlers_motion_acceptance import handle_motion_acceptance_commands
from kinocut.cli.parser.motion_acceptance import add_parsers
from kinocut.errors import MCPVideoError
from kinocut.semantic.models import canonical_digest
from kinocut.server_tool_contracts import _ContractFastMCP
from kinocut.server_tools_motion_acceptance import video_record_motion_acceptance
from tests.test_motion_acceptance import _measured


def _arguments(tmp_path):
    source, report = _measured(tmp_path, [5, 200, 5, 200])
    report["isolated_transitions"] = [
        {
            "start": 1.0,
            "end": 1.1,
            "difference": 90.0,
            "intent_assessed": False,
            "classification": "isolated_transition_candidate",
        }
    ]
    return {
        "report": report,
        "input_path": str(source),
        "reviewer_id": "human:reviewer",
        "source_sha256": report["source_sha256"],
        "report_sha256": canonical_digest(report),
        "watched_intervals": [{"start": 0.0, "end": report["expected_media_end"]}],
        "dispositions": {
            item["review_id"]: "intended_cut" if item["kind"] == "transition" else "purposeful_motion"
            for item in motion_review_items(report)
        },
        "verdict": "accept",
    }


def _parser():
    parser = argparse.ArgumentParser()
    add_parsers(parser.add_subparsers(dest="command"))
    return parser


def _cli_args(arguments):
    return _parser().parse_args(
        [
            "record-motion-acceptance",
            arguments["input_path"],
            "--report-json",
            json.dumps(arguments["report"]),
            "--reviewer-id",
            arguments["reviewer_id"],
            "--source-sha256",
            arguments["source_sha256"],
            "--report-sha256",
            arguments["report_sha256"],
            "--watched-intervals-json",
            json.dumps(arguments["watched_intervals"]),
            "--dispositions-json",
            json.dumps(arguments["dispositions"]),
            "--verdict",
            arguments["verdict"],
        ]
    )


def _invoke(route, arguments, capsys):
    if route == "mcp":
        app = _ContractFastMCP("motion-acceptance-test")
        app.add_tool(video_record_motion_acceptance)
        result = asyncio.run(app._tool_manager.call_tool("video_record_motion_acceptance", arguments))
        if result.get("success") is False:
            raise MCPVideoError(result["error"]["message"], code=result["error"]["code"])
        return result["receipt"]
    assert handle_motion_acceptance_commands(_cli_args(arguments), use_json=True)
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("route", ["mcp", "cli"])
@pytest.mark.parametrize("verdict", ["accept", "reject"])
def test_explicit_complete_review_preserves_receipt_digest_and_unverified_status(tmp_path, capsys, route, verdict):
    arguments = _arguments(tmp_path)
    before = deepcopy(arguments["report"])
    arguments["verdict"] = verdict
    if verdict == "reject":
        arguments["dispositions"] = {key: "needs_fix" for key in arguments["dispositions"]}
    receipt = _invoke(route, arguments, capsys)
    assert receipt["acceptance"] == ("human_granted" if verdict == "accept" else "human_rejected")
    assert receipt["attestation_verified_by_system"] is False
    assert receipt["semantic_assessment_source"] == "human_reviewer"
    assert receipt["receipt_sha256"] == canonical_digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    assert arguments["report"] == before
    assert "approval" not in receipt and "release_approval" not in receipt


def _invalid(arguments, case):
    if case == "source_hash":
        arguments["source_sha256"] = "sha256:" + "b" * 64
    elif case == "report_hash":
        arguments["report_sha256"] = "sha256:" + "b" * 64
    elif case == "reviewer":
        arguments["reviewer_id"] = "model:automatic"
    elif case == "incomplete_watch":
        arguments["watched_intervals"][0]["end"] -= 0.1
    elif case == "watch_gap":
        arguments["watched_intervals"][0]["start"] = 0.1
    elif case == "watch_excess":
        arguments["watched_intervals"][0]["end"] += 0.1
    elif case == "watch_bool":
        arguments["watched_intervals"][0]["start"] = False
    elif case == "watch_nan":
        arguments["watched_intervals"][0]["end"] = float("nan")
    elif case == "watch_numeric_string":
        arguments["watched_intervals"][0]["start"] = "0.0"
    elif case == "dispositions_missing":
        arguments["dispositions"] = {}
    elif case == "dispositions_extra":
        arguments["dispositions"]["unknown"] = "purposeful_motion"
    elif case == "dispositions_wrong_kind":
        arguments["dispositions"] = {key: "purposeful_motion" for key in arguments["dispositions"]}
    elif case == "unresolved":
        arguments["dispositions"] = {key: "needs_fix" for key in arguments["dispositions"]}
    else:
        arguments["report"].update(
            {
                "partial_report": {"coverage_scope": "provided_observations_only"},
                "truncated_report": {"budget_truncation": True},
                "unbound_report": {"source_binding_status": "unbound_observations"},
                "inconclusive_report": {"decoded_media_end": 0.5},
                "measurement_gap": {"gaps": [{"start": 0.1, "end": 0.2}]},
                "unmeasured_report": {"unmeasured_intervals": [{"start": 0.1, "end": 0.2}]},
                "corrupt_report": {"corrupt_intervals": [{"start": 0.1, "end": 0.2}]},
            }[case]
        )
        arguments["report_sha256"] = canonical_digest(arguments["report"])


@pytest.mark.parametrize("route", ["mcp", "cli"])
@pytest.mark.parametrize(
    "case",
    [
        "source_hash",
        "report_hash",
        "reviewer",
        "incomplete_watch",
        "watch_gap",
        "watch_excess",
        "watch_bool",
        "watch_nan",
        "watch_numeric_string",
        "dispositions_missing",
        "dispositions_extra",
        "dispositions_wrong_kind",
        "unresolved",
        "partial_report",
        "truncated_report",
        "unbound_report",
        "inconclusive_report",
        "measurement_gap",
        "unmeasured_report",
        "corrupt_report",
    ],
)
def test_invalid_or_inconclusive_evidence_cannot_grant_acceptance(tmp_path, capsys, route, case):
    arguments = _arguments(tmp_path)
    _invalid(arguments, case)
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, arguments, capsys)
    assert error.value.code == "invalid_motion_review"


@pytest.mark.parametrize("route", ["mcp", "cli"])
def test_replaced_actual_source_cannot_receive_a_stale_receipt(tmp_path, capsys, route):
    from pathlib import Path

    arguments = _arguments(tmp_path)
    Path(arguments["input_path"]).write_bytes(b"replacement after inspection")
    with pytest.raises(MCPVideoError) as error:
        _invoke(route, arguments, capsys)
    assert error.value.code == "invalid_motion_review"


def test_mcp_schema_requires_all_fields_and_rejects_fabricated_verified_receipt_flag(tmp_path):
    app = _ContractFastMCP("motion-acceptance-schema")
    app.add_tool(video_record_motion_acceptance)
    arguments = _arguments(tmp_path)
    schema = app._tool_manager.get_tool("video_record_motion_acceptance").parameters
    assert set(schema["required"]) == set(arguments)
    assert schema["additionalProperties"] is False
    arguments["attestation_verified_by_system"] = True
    rejected = asyncio.run(app.call_tool("video_record_motion_acceptance", arguments))
    assert rejected.isError and rejected.structuredContent["error"]["code"] == "invalid_parameter"


def test_cli_missing_explicit_fields_or_invalid_verdict_never_calls_validator(capsys):
    with pytest.raises(SystemExit) as error:
        _parser().parse_args(["record-motion-acceptance", "film.mp4"])
    assert error.value.code == 2
    help_text = _parser().format_help()
    assert "record-motion-acceptance" in help_text
    assert not handle_motion_acceptance_commands(argparse.Namespace(command="unrelated"), use_json=True)
