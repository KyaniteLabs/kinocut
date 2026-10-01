"""Sound plan admission is bounded before invoking the sound engine."""

from __future__ import annotations

import argparse
import json

import pytest

from kinocut.cli import handlers_sound
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_CLI_JSON_ARTIFACT_BYTES


@pytest.mark.parametrize("raw", [None, "", " \n\t "])
def test_missing_or_blank_plan_preserves_none(raw):
    assert handlers_sound._load_plan_json(raw) is None


def test_valid_inline_and_file_plan_are_forwarded(tmp_path, monkeypatch, capsys):
    plan = {"version": 1, "steps": [{"name": "voice"}]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    calls = []

    def invoke(name, **kwargs):
        calls.append((name, kwargs))
        return {"success": True}

    monkeypatch.setattr(handlers_sound, "_invoke", invoke)
    for raw in (json.dumps(plan), str(path)):
        args = argparse.Namespace(command="sound-plan-validate", plan_json=raw)
        assert handlers_sound.handle_sound_commands(args, use_json=True)
    assert calls == [("sound-plan-validate", {"plan": plan})] * 2
    assert capsys.readouterr().out.count('"success": true') == 2


@pytest.mark.parametrize("command", ["sound-plan-validate", "sound-voice-batch"])
@pytest.mark.parametrize("kind", ["file", "inline", "unicode-inline"])
def test_oversized_plan_is_rejected_before_invoke(tmp_path, monkeypatch, kind, command):
    text = '{"secret":"' + "x" * MAX_CLI_JSON_ARTIFACT_BYTES + '"}'
    if kind == "file":
        path = tmp_path / "private-plan.json"
        path.write_text(text, encoding="utf-8")
        raw = str(path)
    elif kind == "unicode-inline":
        raw = '{"secret":"' + "雪" * (MAX_CLI_JSON_ARTIFACT_BYTES // 3 + 1) + '"}'
        assert len(raw) < MAX_CLI_JSON_ARTIFACT_BYTES
    else:
        raw = text

    def forbidden(*args, **kwargs):
        pytest.fail("oversized plan must not invoke the sound engine")

    monkeypatch.setattr(handlers_sound, "_invoke", forbidden)
    args = argparse.Namespace(command=command, plan_json=raw, request_json=None, project_root=None)
    with pytest.raises(MCPVideoError) as failure:
        handlers_sound.handle_sound_commands(args, use_json=True)
    assert failure.value.error_type == "validation_error"
    assert failure.value.code == "invalid_json_artifact"
    assert "private-plan" not in str(failure.value)
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "payload",
    [b'{"secret":', b'{"secret":"\xff"}', b'{"secret":' + b"[" * 10000 + b"]" * 10000 + b"}"],
    ids=["malformed-json", "malformed-utf8", "deep-json"],
)
def test_invalid_file_plan_is_typed_and_redacted(tmp_path, monkeypatch, payload):
    path = tmp_path / "private-plan.json"
    path.write_bytes(payload)
    monkeypatch.setattr(handlers_sound, "_invoke", lambda *a, **kw: pytest.fail("invalid plan was invoked"))
    args = argparse.Namespace(command="sound-plan-validate", plan_json=str(path))
    with pytest.raises(MCPVideoError) as failure:
        handlers_sound.handle_sound_commands(args, use_json=True)
    assert failure.value.code == "invalid_json_artifact"
    assert failure.value.error_type == "validation_error"
    assert str(path) not in str(failure.value)
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "raw",
    ['{"secret":', '{"secret":"\ud800"}', '{"secret":' + "[" * 10000 + "]" * 10000 + "}"],
    ids=["malformed-json", "malformed-unicode", "deep-json"],
)
def test_invalid_inline_plan_is_typed_and_redacted(raw):
    with pytest.raises(MCPVideoError) as failure:
        handlers_sound._load_plan_json(raw)
    assert failure.value.code == "invalid_json_artifact"
    assert failure.value.error_type == "validation_error"
    assert "secret" not in str(failure.value)


def test_file_admission_checks_size_before_json_parse(tmp_path, monkeypatch):
    import kinocut.json_artifacts as artifacts

    path = tmp_path / "oversize.json"
    with path.open("wb") as handle:
        handle.truncate(MAX_CLI_JSON_ARTIFACT_BYTES + 1)
    monkeypatch.setattr(artifacts.json, "loads", lambda *a, **kw: pytest.fail("oversized file parsed"))
    with pytest.raises(MCPVideoError, match="byte limit"):
        handlers_sound._load_plan_json(str(path))


def test_inline_plan_ceiling_counts_untrimmed_input(monkeypatch):
    monkeypatch.setattr(handlers_sound, "MAX_CLI_JSON_ARTIFACT_BYTES", 16)
    with pytest.raises(MCPVideoError, match="byte limit"):
        handlers_sound._load_plan_json(" " * 16 + "{}")


@pytest.mark.parametrize("file_plan", [False, True])
def test_exact_byte_ceiling_is_inclusive(tmp_path, file_plan):
    text = '{"text":"' + "x" * (MAX_CLI_JSON_ARTIFACT_BYTES - len('{"text":""}')) + '"}'
    assert len(text.encode("utf-8")) == MAX_CLI_JSON_ARTIFACT_BYTES
    if file_plan:
        path = tmp_path / "plan.json"
        path.write_text(text, encoding="utf-8")
        raw = str(path)
    else:
        raw = text
    assert handlers_sound._load_plan_json(raw) == {"text": "x" * (MAX_CLI_JSON_ARTIFACT_BYTES - 11)}
