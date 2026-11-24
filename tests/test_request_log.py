"""Opt-in request log: redaction rules, opt-in gate, wire-path capture, reader.

Covers the contract of `kinocut.request_log` (card t_d677705e):

* default off, enabled by `KINOCUT_REQUEST_LOG` (flag or path),
* a request containing a file path and a credential-shaped string is logged
  with both redacted,
* direct and family MCP invocations both capture `chosen_operation`,
* discovery tools are not logged,
* harvesting via `python -m kinocut.request_log` re-emits JSONL,
* logging failures never break the tool call.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from kinocut import request_log
from kinocut.request_log import iter_records, log_invocation, main, redact_text, resolve_log_path

JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
SECRET_KEY = "sk-abc123def456ghi789jkl"  # noqa: S105 — synthetic test token, never a real credential


def _call(name: str, arguments: dict) -> object:
    import kinocut.server  # noqa: F401 — surface configured by conftest

    from kinocut.server_app import mcp

    return asyncio.run(mcp.call_tool(name, arguments))


def _records(path: Path) -> list[dict]:
    return iter_records(path)


@pytest.fixture
def enabled_log(tmp_path, monkeypatch):
    """Enabled request log at an explicit path; returns the path."""
    log_path = tmp_path / "request_log.jsonl"
    monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(log_path))
    return log_path


@pytest.mark.parametrize(
    ("text", "forbidden", "must_contain"),
    [
        ("trim /home/alice/secret.mp4 please", ["/home/alice", "secret.mp4"], ["<path>"]),
        ("source is ~/Movies/clip.mp4", ["Movies", "clip.mp4"], ["<path>"]),
        ("see C:\\Users\\bob\\video.mp4 ok", ["Users", "video.mp4"], ["<path>"]),
        ("fetch https://example.com/pull?token=abc123def456 now", ["abc123def456"], ["example.com/pull"]),
        ("plain https://example.com/feed stays", [], ["https://example.com/feed"]),
        ("feed https://user:secretpw@example.com/x", ["secretpw", "user"], []),
        (f"use api_key={SECRET_KEY} now", [SECRET_KEY], ["<redacted>"]),
        ('{"token": "HGjk2s7dJsl28Dkq1Zx0p4Vn6"}', ["HGjk2s7dJsl28Dkq1Zx0p4Vn6"], []),
        ("password: hunter2000", ["hunter2000"], []),
        ("token='abc987xyz654'", ["abc987xyz654"], []),
        (f"Authorization: Bearer {JWT}", [JWT], []),
        ("contact bob@example.com or @alice_dev", ["bob@example.com", "@alice_dev"], ["<email>", "<handle>"]),
        ("use AKIAIOSFODNN7EXAMPLE key", ["AKIAIOSFODNN7EXAMPLE"], []),
        ("path is /home/alice/videos no ext", ["/home/alice/videos"], ["<path>"]),
        ("relative assets/clips/intro.mp4 ok", ["assets/clips/intro.mp4"], ["<path>"]),
        ("bare clip.mp4 file", ["clip.mp4"], ["<path>"]),
        ("hash 0123456789abcdef0123456789abcdef end", ["0123456789abcdef0123456789abcdef"], []),
        # Prose and word-shaped text survive.
        ("and/or nothing 24/7", [], ["and/or", "24/7"]),
        ("please trim the video and add a title", [], ["trim the video and add a title"]),
    ],
)
def test_redaction_table(text: str, forbidden: list[str], must_contain: list[str]) -> None:
    out = redact_text(text)
    for needle in forbidden:
        assert needle not in out, f"{needle!r} survived redaction: {out!r}"
    for needle in must_contain:
        assert needle in out, f"{needle!r} missing from redacted text: {out!r}"


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(request_log.ENV_REQUEST_LOG, raising=False)
    monkeypatch.setenv("KINOCUT_STATE_DIR", str(tmp_path))
    assert resolve_log_path() is None
    _call("video_intent", {"verb": "trim", "goal": "trim /home/alice/secret.mp4"})
    assert not (tmp_path / "request_log.jsonl").exists()


def test_falsy_values_disable(monkeypatch) -> None:
    for value in ("", "0", "false", "no", "off", "OFF"):
        monkeypatch.setenv(request_log.ENV_REQUEST_LOG, value)
        assert resolve_log_path() is None, value


def test_truthy_flag_uses_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(request_log.ENV_REQUEST_LOG, "1")
    monkeypatch.setenv("KINOCUT_STATE_DIR", str(tmp_path))
    assert resolve_log_path() == tmp_path / "request_log.jsonl"


def test_explicit_path_is_honored(monkeypatch, tmp_path) -> None:
    target = tmp_path / "nested" / "corpus.jsonl"
    monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(target))
    assert resolve_log_path() == target


def test_direct_invocation_logs_redacted_pair(enabled_log: Path) -> None:
    """Acceptance: file path and credential in the request are both redacted."""
    result = _call(
        "video_intent",
        {
            "verb": "trim",
            "goal": f"use api_key={SECRET_KEY} to trim /home/alice/secret.mp4",
            "source": "/home/alice/secret.mp4",
        },
    )
    assert result is not None
    records = _records(enabled_log)
    assert len(records) == 1
    record = records[0]
    assert set(record) == {"request_text", "chosen_operation", "timestamp", "session_id"}
    assert record["chosen_operation"] == "video_intent"
    request_text = record["request_text"]
    assert "/home/alice/secret.mp4" not in request_text
    assert SECRET_KEY not in request_text
    assert "<path>" in request_text
    assert "<redacted>" in request_text
    parsed_time = datetime.fromisoformat(record["timestamp"])
    assert parsed_time.tzinfo is not None
    assert record["session_id"]


@pytest.mark.parametrize("flat", [False, True])
def test_family_invocation_logs_operation(enabled_log: Path, flat: bool) -> None:
    from kinocut.tool_registry import configure_tool_surface

    params = {"verb": "trim", "goal": "trim /home/alice/secret.mp4 with token=abc987xyz654"}
    payload = params if flat else {"params": params}
    try:
        configure_tool_surface()  # default surface: typed family tools
        result = _call("video_plan_ops", {"operation": "video_intent", **payload})
    finally:
        configure_tool_surface("all")  # restore the session-wide full catalog
    assert result is not None
    records = _records(enabled_log)
    assert len(records) == 1
    record = records[0]
    assert record["chosen_operation"] == "video_intent"
    assert "/home/alice/secret.mp4" not in record["request_text"]
    assert "abc987xyz654" not in record["request_text"]
    assert '"params":{"verb":"trim"' in record["request_text"]


def test_discovery_tools_are_not_operations(enabled_log: Path) -> None:
    _call("search_tools", {"query": "trim"})
    _call("video_intent", {"verb": "trim"})
    records = _records(enabled_log)
    assert [r["chosen_operation"] for r in records] == ["video_intent"]


def test_session_id_is_stable_per_process(enabled_log: Path) -> None:
    log_invocation("video_info", {"input_path": "/home/alice/a.mp4"})
    log_invocation("video_info", {"input_path": "/home/alice/b.mp4"})
    records = _records(enabled_log)
    assert len(records) == 2
    assert records[0]["session_id"] == records[1]["session_id"]


def test_reader_emits_jsonl_and_skips_malformed_lines(enabled_log: Path, capsys) -> None:
    log_invocation("video_info", {"input_path": "/home/alice/a.mp4"})
    log_invocation("video_trim", {"input_path": "/home/alice/b.mp4"})
    enabled_log.write_text(enabled_log.read_text() + "{not json\n", encoding="utf-8")
    exit_code = main(["--path", str(enabled_log)])
    assert exit_code == 0
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["chosen_operation"] for r in emitted] == ["video_info", "video_trim"]


def test_reader_limit(enabled_log: Path, capsys) -> None:
    log_invocation("video_info", {"input_path": "/home/alice/a.mp4"})
    log_invocation("video_trim", {"input_path": "/home/alice/b.mp4"})
    main(["--path", str(enabled_log), "--limit", "1"])
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["chosen_operation"] for r in emitted] == ["video_trim"]


def test_missing_log_reads_empty(tmp_path) -> None:
    assert iter_records(tmp_path / "absent.jsonl") == []


def test_log_failure_never_breaks_the_call(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file", encoding="utf-8")
    monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(blocker / "nested" / "log.jsonl"))
    result = _call("video_intent", {"verb": "trim"})
    assert result is not None  # the call succeeded despite the unwritable log


def test_request_text_is_truncated(enabled_log: Path) -> None:
    # Spaced prose avoids the dense-token redaction rule, so the size cap is
    # what bounds the record. (An opaque 13k-char blob is *redacted*, not
    # truncated — stronger privacy, different code path.)
    huge = "please trim this clip quietly " * 600
    log_invocation("video_intent", {"goal": huge})
    record = _records(enabled_log)[0]
    assert len(record["request_text"].encode("utf-8")) <= request_log._MAX_REQUEST_TEXT
    assert "truncated" in record["request_text"]


def test_request_text_enforces_utf8_byte_budget_with_multibyte_chars(enabled_log: Path) -> None:
    multibyte = "剪辑视频 🎬 " * 1200
    log_invocation("video_intent", {"goal": multibyte})
    record = _records(enabled_log)[0]
    assert len(record["request_text"].encode("utf-8")) <= request_log._MAX_REQUEST_TEXT
    assert "bytes truncated" in record["request_text"]


def test_sensitive_keys_and_spaced_paths_are_fully_redacted(enabled_log: Path) -> None:
    log_invocation(
        "video_trim",
        {
            "refresh_token": "short123",
            "api_key": "tiny",
            "input_path": "/Users/alice/My Private Project/final cut 2026.mp4",
            "clips": ["/Users/alice/Vacation Clip One.mp4", "/Users/alice/Vacation Clip Two.mp4"],
        },
    )
    text = _records(enabled_log)[0]["request_text"]
    for leaked in (
        "short123",
        "tiny",
        "My Private Project",
        "final cut 2026",
        "Vacation Clip One",
        "Vacation Clip Two",
    ):
        assert leaked not in text
    assert "<redacted>" in text
    assert "<path>" in text


def test_unterminated_pem_and_oversized_input_stay_linear(enabled_log: Path) -> None:
    import time

    adversarial_pem = "-----BEGIN RSA PRIVATE KEY----- " * 5000 + "SUPERSECRETBODY"
    start = time.monotonic()
    out = redact_text(adversarial_pem)
    assert time.monotonic() - start < 0.5
    assert "SUPERSECRETBODY" not in out
    assert "<redacted>" in out

    start = time.monotonic()
    log_invocation("video_intent", {"goal": "trim clip " * 200_000})
    assert time.monotonic() - start < 0.5
    record = _records(enabled_log)[0]
    assert len(record["request_text"].encode("utf-8")) <= request_log._MAX_REQUEST_TEXT


def test_unsafe_log_destinations_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    # 1. Symlink destination must not be followed.
    victim = tmp_path / "victim.jsonl"
    victim.write_text("KEEP\n", encoding="utf-8")
    link = tmp_path / "link.jsonl"
    link.symlink_to(victim)
    monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(link))
    log_invocation("video_info", {"input_path": "/tmp/a.mp4"})
    assert victim.read_text(encoding="utf-8") == "KEEP\n"

    # 2. World-readable existing file must be rejected on POSIX.
    if os.name == "posix":
        world = tmp_path / "world.jsonl"
        world.write_text("", encoding="utf-8")
        world.chmod(0o644)
        monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(world))
        log_invocation("video_info", {"input_path": "/tmp/a.mp4"})
        assert world.read_text(encoding="utf-8") == ""

        # 3. FIFO must fail fast without blocking.
        fifo = tmp_path / "pipe.jsonl"
        os.mkfifo(fifo, 0o600)
        monkeypatch.setenv(request_log.ENV_REQUEST_LOG, str(fifo))
        log_invocation("video_info", {"input_path": "/tmp/a.mp4"})


def test_unrecognized_or_cross_family_operation_is_not_logged(enabled_log: Path) -> None:
    from kinocut.tool_registry import configure_tool_surface

    try:
        configure_tool_surface()
        _call("video_plan_ops", {"operation": "bogus_" + "x" * 5000, "params": {}})
        _call("video_plan_ops", {"operation": "video_trim", "params": {}})
    finally:
        configure_tool_surface("all")
    assert _records(enabled_log) == []
