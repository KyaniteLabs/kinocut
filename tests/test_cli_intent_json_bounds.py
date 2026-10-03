"""Intent/review JSON admission fails before engine or approval work."""

import json
import subprocess
import sys

import pytest

from kinocut.cli.handlers_intent import handle_intent_commands
from kinocut.cli.parser import build_parser
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_CLI_JSON_ARTIFACT_BYTES


@pytest.mark.parametrize("command", ["propose-broll", "review-decide", "propose-mutations", "otio-export"])
def test_file_artifacts_reject_oversize_before_engine(command, tmp_path):
    path = tmp_path / "artifact.json"
    with path.open("wb") as handle:
        handle.truncate(MAX_CLI_JSON_ARTIFACT_BYTES + 1)
    tail = ["accept"] if command == "review-decide" else []
    if command == "otio-export":
        tail = ["--output", str(tmp_path / "out.json")]
    args = build_parser().parse_args([command, str(path), *tail])
    with pytest.raises(MCPVideoError, match="byte limit"):
        handle_intent_commands(args, use_json=True)
    assert not (tmp_path / "out.json").exists()


def test_broll_valid_list_keeps_human_review_policy(tmp_path, capsys):
    import json

    path = tmp_path / "segments.json"
    path.write_text("[]")
    args = build_parser().parse_args(["propose-broll", str(path)])
    assert handle_intent_commands(args, use_json=True)
    result = json.loads(capsys.readouterr().out)
    assert result["apply_policy"] == "human_review_required"
    assert result["proposal_count"] == 0


@pytest.mark.parametrize(
    "raw",
    ['{"private":', "[" * 10000 + "]" * 10000, " " * (MAX_CLI_JSON_ARTIFACT_BYTES + 1)],
    ids=["syntax", "recursion", "size"],
)
def test_intent_inline_parameters_fail_with_typed_redacted_error(raw):
    args = build_parser().parse_args(["intent", "reformat_vertical", "--params-json", raw])
    with pytest.raises(MCPVideoError) as error:
        handle_intent_commands(args, use_json=True)
    assert error.value.code == "invalid_json_artifact"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("value", [[], "private-review-secret", 7, 1.5, True, False, None])
def test_review_non_object_rejected_before_any_decision_or_render(value, tmp_path, monkeypatch):
    path = tmp_path / "private-review.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "out.mp4"

    def forbidden(*args, **kwargs):
        pytest.fail("Non-object artifact reached a decision or render delegate")

    monkeypatch.setattr("kinocut.watching.decide_review", forbidden)
    monkeypatch.setattr("kinocut.te.decide_sphere_plan", forbidden)
    monkeypatch.setattr("kinocut.te.render_sphere_plan", forbidden)
    args = build_parser().parse_args(["review-decide", str(path), "accept", "--output", str(output)])
    with pytest.raises(MCPVideoError) as error:
        handle_intent_commands(args, use_json=True)
    assert error.value.error_type == "validation_error"
    assert error.value.code == "invalid_review_run"
    assert "private" not in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("value", [[], "private-review-secret", 7, True, None])
def test_actual_cli_non_object_review_has_typed_redacted_failure(value, tmp_path):
    path = tmp_path / "private-review.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", "review-decide", str(path), "accept"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1 and result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["success"] is False
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["code"] == "invalid_review_run"
    assert "private" not in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize("blocked", [False, True])
def test_normal_object_review_keeps_explicit_override_policy(tmp_path, capsys, blocked):
    path = tmp_path / "review.json"
    review = {"artifact_kind": "review_run", "blocked": blocked, "verdict": "fail" if blocked else "pass"}
    path.write_text(json.dumps(review), encoding="utf-8")
    args = build_parser().parse_args(["review-decide", str(path), "accept"])
    if blocked:
        with pytest.raises(MCPVideoError) as error:
            handle_intent_commands(args, use_json=True)
        assert error.value.code == "accept_requires_reason"
    else:
        assert handle_intent_commands(args, use_json=True)
        result = json.loads(capsys.readouterr().out)
        assert result["decision"] == "accept" and result["review_run"] == review
