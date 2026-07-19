"""Behavior tests for the namespaced CLI argv router (#388, T7a).

These tests exercise the ``kino <group> <action> ...`` -> ``kino <flat> ...`` rewrite
that ``kinocut.__main__._rewrite_namespaced_argv`` performs before
``build_parser().parse_args()`` runs. They do NOT depend on a new argparse subparser
being added; the flat 130-command surface stays authoritative.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from kinocut.__main__ import _rewrite_namespaced_argv
from kinocut.cli.namespaces import NAMESPACED_ALIASES
from kinocut.cli.parser import build_parser
from tests.test_public_surface import EXPECTED_CLI_COMMANDS


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kinocut", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_no_dangling_aliases_every_target_is_a_registered_flat_command():
    """Every (group, action) alias must target a real flat subcommand — no dangling aliases."""

    dangling = sorted(
        f"{group} {action} -> {flat}"
        for (group, action), flat in NAMESPACED_ALIASES.items()
        if flat not in EXPECTED_CLI_COMMANDS
    )
    assert not dangling, f"dangling namespace aliases: {dangling}"


@pytest.mark.parametrize(
    ("group", "action", "flat"),
    [(group, action, flat) for (group, action), flat in sorted(NAMESPACED_ALIASES.items())],
    ids=[f"{group}-{action}" for group, action in sorted(NAMESPACED_ALIASES)],
)
def test_every_aivideo_alias_rewrites_to_its_flat_target(group: str, action: str, flat: str):
    """All seven aivideo aliases route to the matching flat command, preserving trailing argv."""

    rewritten = _rewrite_namespaced_argv([group, action, "PROJECT", "--extra", "value"])
    assert rewritten == [flat, "PROJECT", "--extra", "value"]


def test_format_json_before_group_is_preserved():
    """The ``--format VALUE`` global and its value survive; the group/action still rewrites."""

    rewritten = _rewrite_namespaced_argv(["--format", "json", "aivideo", "verdict", "PROJECT"])
    assert rewritten == ["--format", "json", "video-verdict", "PROJECT"]


def test_format_equals_form_is_recognized_as_a_value_option():
    """``--format=json`` is one token; the rewriter skips it without misreading ``json`` as a group."""

    rewritten = _rewrite_namespaced_argv(["--format=json", "aivideo", "verdict"])
    assert rewritten == ["--format=json", "video-verdict"]


def test_short_verbose_before_group_is_preserved():
    """Boolean ``-v`` is skipped, the group/action still rewrites, and the flag is retained."""

    rewritten = _rewrite_namespaced_argv(["-v", "aivideo", "verdict", "PROJECT"])
    assert rewritten == ["-v", "video-verdict", "PROJECT"]


def test_long_verbose_before_group_is_preserved():
    rewritten = _rewrite_namespaced_argv(["--verbose", "aivideo", "salvage", "PROJECT"])
    assert rewritten == ["--verbose", "video-salvage", "PROJECT"]


def test_version_global_is_skipped_not_misread_as_group():
    """``--version`` is a boolean global; the rewriter must not treat the next token as its value."""

    # With a group/action after --version, the rewrite still fires.
    rewritten = _rewrite_namespaced_argv(["--version", "aivideo", "verdict"])
    assert rewritten == ["--version", "video-verdict"]
    # Bare --version falls through untouched.
    assert _rewrite_namespaced_argv(["--version"]) == ["--version"]


def test_mcp_global_is_skipped_not_misread_as_group():
    rewritten = _rewrite_namespaced_argv(["--mcp", "aivideo", "verdict"])
    assert rewritten == ["--mcp", "video-verdict"]


def test_unknown_group_falls_through_unchanged():
    """Unknown first positional token is left for argparse to reject natively."""

    assert _rewrite_namespaced_argv(["unknown", "verdict", "PROJECT"]) == ["unknown", "verdict", "PROJECT"]


def test_unknown_action_falls_through_unchanged():
    """Known group with unknown action falls through unchanged."""

    assert _rewrite_namespaced_argv(["aivideo", "nope", "PROJECT"]) == ["aivideo", "nope", "PROJECT"]


def test_group_without_action_falls_through_unchanged():
    """A lone group token has nothing to pair with; defer to argparse."""

    assert _rewrite_namespaced_argv(["aivideo"]) == ["aivideo"]


def test_option_value_is_not_mistaken_for_a_group():
    """``--format`` consumes its value, so a value like ``text`` never becomes the candidate group."""

    # `--format text aivideo` -> aivideo has no paired action; falls through.
    assert _rewrite_namespaced_argv(["--format", "text", "aivideo"]) == ["--format", "text", "aivideo"]


def test_unknown_option_short_circuits_without_rewriting():
    """An unrecognized option makes the prefix ambiguous; the rewriter bails entirely."""

    argv = ["--unknown-flag", "value", "aivideo", "verdict"]
    assert _rewrite_namespaced_argv(argv) == argv


def test_flat_command_set_remains_130():
    """The flat subcommand set is the same 130-command surface; no new parser was added."""

    assert len(EXPECTED_CLI_COMMANDS) == 130
    assert len(NAMESPACED_ALIASES) == 7


def test_parser_does_not_register_an_aivideo_subparser():
    """Grouped routing reuses flat subparsers; no `aivideo` subparser is created."""

    import argparse as _argparse

    parser = build_parser()
    subparsers_action = next(action for action in parser._actions if isinstance(action, _argparse._SubParsersAction))
    choices = set(subparsers_action.choices)
    assert "aivideo" not in choices
    assert choices == EXPECTED_CLI_COMMANDS


def test_grouped_route_exposes_target_help():
    """`kino aivideo verdict --help` rewrites so argparse prints the flat command's help."""

    result = _cli("aivideo", "verdict", "--help")
    assert result.returncode == 0, result.stderr
    # The flat command's help is shown — its prog line and required positional appear verbatim.
    assert "video-verdict" in result.stdout
    assert "--verdict-json" in result.stdout


def test_group_help_does_not_add_aivideo_to_top_level_command_list():
    """`kino --help` still lists exactly the flat 130 commands — no aivideo entry."""

    result = _cli("--help")
    assert result.returncode == 0, result.stderr
    command_lists = re.findall(r"\{([^}]+)\}", result.stdout)
    command_list = max(command_lists, key=lambda value: len(value.split(",")))
    help_commands = set(command_list.split(","))
    assert help_commands == EXPECTED_CLI_COMMANDS
    assert "aivideo" not in help_commands
