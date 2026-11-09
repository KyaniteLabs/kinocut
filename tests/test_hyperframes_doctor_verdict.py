"""hyperframes-doctor reports a readable verdict that tracks required checks (#675)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest


def _doctor_stdout(checks: list[dict]) -> str:
    return json.dumps({"ok": all(c["ok"] for c in checks), "platform": "linux", "checks": checks})


def _patch_doctor(monkeypatch, checks: list[dict]) -> None:
    completed = subprocess.CompletedProcess(args=["hyperframes", "doctor"], returncode=0, stdout=_doctor_stdout(checks))
    monkeypatch.setattr("kinocut.hyperframes_ops._hyperframes_op", lambda *_a, **_k: (completed, "/tmp"))
    monkeypatch.setattr(
        "kinocut.cli.handlers_hyperframes._with_spinner",
        lambda _label, fn, *args, **kwargs: fn(*args, **kwargs),
    )


def _run(use_json: bool):
    from kinocut.cli.handlers_hyperframes import handle_hyperframes_commands

    return handle_hyperframes_commands(SimpleNamespace(command="hyperframes-doctor"), use_json=use_json)


REQUIRED_FAIL = [
    {"name": "Node.js", "ok": True, "detail": "v22.11.0"},
    {"name": "Chrome", "ok": False, "detail": "Not found", "hint": "npx hyperframes browser ensure"},
    {"name": "whisper-cpp", "ok": False, "detail": "Not found (optional — needed for transcription)"},
]

OPTIONAL_ONLY_FAIL = [
    {"name": "Node.js", "ok": True, "detail": "v22.11.0"},
    {"name": "whisper-cpp", "ok": False, "detail": "Not found (optional — needed for transcription)"},
    {"name": "TTS (Kokoro)", "ok": False, "detail": "Not installed"},
    {"name": "Docker", "ok": False, "detail": "Not found"},
]


def test_failing_required_check_exits_nonzero_with_readable_text(monkeypatch, capsys):
    _patch_doctor(monkeypatch, REQUIRED_FAIL)

    with pytest.raises(SystemExit) as exc:
        _run(use_json=False)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "success=" not in out
    assert "stdout=" not in out
    assert "Chrome" in out
    assert "npx hyperframes browser ensure" in out
    assert "Not ready" in out


def test_failing_required_check_json_success_false(monkeypatch, capsys):
    _patch_doctor(monkeypatch, REQUIRED_FAIL)

    with pytest.raises(SystemExit):
        _run(use_json=True)

    data = json.loads(capsys.readouterr().out)
    assert data["success"] is False
    assert data["data"]["failed_required"] == ["Chrome"]
    assert data["data"]["failed_optional"] == ["whisper-cpp"]


def test_optional_failures_alone_stay_successful(monkeypatch, capsys):
    _patch_doctor(monkeypatch, OPTIONAL_ONLY_FAIL)

    assert _run(use_json=True) is True

    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["data"]["ok"] is False  # upstream verdict is preserved untouched
    assert data["data"]["required_ok"] is True
    assert data["data"]["failed_optional"] == ["whisper-cpp", "TTS (Kokoro)", "Docker"]


def test_mcp_doctor_reports_required_failure(monkeypatch):
    _patch_doctor(monkeypatch, REQUIRED_FAIL)
    from kinocut.server_tools_hyperframes import hyperframes_doctor

    result = hyperframes_doctor()
    assert result["success"] is False
    assert result["data"]["required_ok"] is False


def test_doctor_formatter_is_scoped_to_doctor_command():
    import inspect
    import re

    from kinocut.cli import handlers_hyperframes

    src = inspect.getsource(handlers_hyperframes)
    calls = len(re.findall(r"_out\(\s*r,\s*j,\s*_format_hyperframes_doctor", src))
    assert calls == 1, f"doctor formatter must only render hyperframes-doctor, found {calls} uses"
