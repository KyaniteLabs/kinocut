"""Agent-mode output policy (#53)."""

from __future__ import annotations

from kinocut.cli.runner import resolve_use_json


def test_text_is_never_auto_json():
    assert resolve_use_json("text", stdout_isatty=True) is False
    assert resolve_use_json("text", stdout_isatty=False) is False


def test_json_is_always_json_regardless_of_tty():
    assert resolve_use_json("json", stdout_isatty=True) is True
    assert resolve_use_json("json", stdout_isatty=False) is True


def test_auto_switches_to_json_when_stdout_is_piped():
    # Non-interactive (agent/subprocess) callers get JSON without an explicit flag.
    assert resolve_use_json("auto", stdout_isatty=False) is True


def test_auto_stays_text_when_stdout_is_a_tty():
    assert resolve_use_json("auto", stdout_isatty=True) is False


def test_explicit_format_wins_over_auto_detection():
    # An explicit json/text always overrides the auto non-TTY detection.
    assert resolve_use_json("json", stdout_isatty=True) is True
    assert resolve_use_json("text", stdout_isatty=False) is False
