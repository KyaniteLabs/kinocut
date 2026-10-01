"""Intent/review JSON admission fails before engine or approval work."""

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
