"""Tests for CLI common helpers."""

import json
from unittest.mock import MagicMock

import pytest

from mcp_video.cli.common import _auto_output, _parse_json_arg, _with_spinner, output_json


class TestAutoOutput:
    def test_generates_suffixed_path(self):
        assert _auto_output("/tmp/video.mp4", "trimmed") == "/tmp/video_trimmed.mp4"
        assert _auto_output("video", "out") == "video_out"


class TestOutputJson:
    def test_prints_dict(self, capsys):
        output_json({"key": "value"})
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"key": "value"}

    def test_prints_model_dump(self, capsys):
        obj = MagicMock()
        obj.model_dump.return_value = {"data": 123}
        output_json(obj)
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"data": 123}


class TestParseJsonArg:
    def test_parses_valid_json(self):
        assert _parse_json_arg('{"a": 1}') == {"a": 1}
        assert _parse_json_arg("[1, 2, 3]") == [1, 2, 3]

    def test_invalid_json_exits_text(self, capsys):
        with pytest.raises(SystemExit):
            _parse_json_arg("not json", arg_name="timeline")
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err or "Invalid JSON" in captured.out

    def test_invalid_json_exits_json(self, capsys):
        with pytest.raises(SystemExit):
            _parse_json_arg("not json", arg_name="timeline", json_mode=True)
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["success"] is False

    @pytest.mark.parametrize(
        "raw", ["[" * 2000 + "]" * 2000, '"\ud800"', " " * 1_048_577], ids=["deep", "invalid-unicode", "oversize"]
    )
    def test_admission_errors_are_bounded_and_redacted(self, raw, capsys):
        with pytest.raises(SystemExit) as error:
            _parse_json_arg(raw, arg_name="timeline", json_mode=True)
        assert error.value.code == 1
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error"]["code"] == "invalid_json"
        assert len(captured.out) < 500


class TestWithSpinner:
    def test_calls_function(self):
        mock_fn = MagicMock(return_value="ok")
        result = _with_spinner("Working...", mock_fn, "arg1", kw="val")
        assert result == "ok"
        mock_fn.assert_called_once_with("arg1", kw="val")
