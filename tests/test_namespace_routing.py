"""Behavior tests for the namespaced CLI argv router (#388, T7a; #390, T7b; #391, T7c).

These tests exercise the ``kino <group> <action> ...`` -> ``kino <flat> ...`` rewrite
that ``kinocut.__main__._rewrite_namespaced_argv`` performs before
``build_parser().parse_args()`` runs. They do NOT depend on a new argparse subparser
being added; the flat 130-command surface stays authoritative. T7a added the seven
``aivideo`` aliases; T7b adds the nine ``audio`` aliases; T7c adds the five ``qa``
aliases on top of the merged router.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from kinocut.__main__ import _rewrite_namespaced_argv
from kinocut.cli.namespaces import NAMESPACED_ALIASES, namespaced_groups
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
def test_every_namespaced_alias_rewrites_to_its_flat_target(group: str, action: str, flat: str):
    """Every (group, action) alias rewrites to its flat command, preserving trailing argv.

    Covers all 21 aliases: the seven ``aivideo`` paths (T7a), the nine ``audio``
    paths (T7b), and the five ``qa`` paths (T7c). Group/action-specific counts are
    pinned by the dedicated tests below.
    """

    rewritten = _rewrite_namespaced_argv([group, action, "PROJECT", "--extra", "value"])
    assert rewritten == [flat, "PROJECT", "--extra", "value"]


# Explicit per-group coverage so a future addition to any group is caught.

AIVIDEO_ALIASES: dict[tuple[str, str], str] = {
    ("aivideo", "verdict"): "video-verdict",
    ("aivideo", "acceptance"): "video-acceptance-eval",
    ("aivideo", "salvage"): "video-salvage",
    ("aivideo", "body-swap"): "video-body-swap",
    ("aivideo", "ingest"): "video-ingest",
    ("aivideo", "preflight"): "video-preflight",
    ("aivideo", "inspect"): "video-inspect-temporal",
}

AUDIO_ALIASES: dict[tuple[str, str], str] = {
    ("audio", "normalize"): "normalize-audio",
    ("audio", "synthesize"): "audio-synthesize",
    ("audio", "compose"): "audio-compose",
    ("audio", "preset"): "audio-preset",
    ("audio", "sequence"): "audio-sequence",
    ("audio", "effects"): "audio-effects",
    ("audio", "add-generated"): "video-add-generated-audio",
    ("audio", "spatial"): "video-audio-spatial",
    ("audio", "bed"): "audio-bed",
}

QA_ALIASES: dict[tuple[str, str], str] = {
    ("qa", "auto-chapters"): "video-auto-chapters",
    ("qa", "info-detailed"): "video-info-detailed",
    ("qa", "check"): "video-quality-check",
    ("qa", "design-check"): "video-design-quality-check",
    ("qa", "fix-design"): "video-fix-design-issues",
}


def test_aivideo_group_keeps_exactly_seven_aliases():
    """The T7a aivideo group is unchanged: exactly its seven known aliases."""

    aivideo = {k: v for k, v in NAMESPACED_ALIASES.items() if k[0] == "aivideo"}
    assert aivideo == AIVIDEO_ALIASES
    assert len(aivideo) == 7


@pytest.mark.parametrize(
    ("action", "flat"),
    [(action, flat) for (_, action), flat in sorted(AUDIO_ALIASES.items())],
    ids=[f"audio-{action}" for _, action in sorted(AUDIO_ALIASES)],
)
def test_every_audio_alias_rewrites_to_its_flat_target(action: str, flat: str):
    """All nine T7b audio aliases route to the matching flat command, preserving trailing argv."""

    rewritten = _rewrite_namespaced_argv(["audio", action, "PROJECT", "--extra", "value"])
    assert rewritten == [flat, "PROJECT", "--extra", "value"]
    # The flat target is still directly parseable as a registered subcommand.
    assert flat in EXPECTED_CLI_COMMANDS


@pytest.mark.parametrize(
    ("action", "flat"),
    [(action, flat) for (_, action), flat in sorted(QA_ALIASES.items())],
    ids=[f"qa-{action}" for _, action in sorted(QA_ALIASES)],
)
def test_every_qa_alias_rewrites_to_its_flat_target(action: str, flat: str):
    """All five T7c qa aliases route to the matching flat command, preserving trailing argv."""

    rewritten = _rewrite_namespaced_argv(["qa", action, "PROJECT", "--extra", "value"])
    assert rewritten == [flat, "PROJECT", "--extra", "value"]
    # The flat target is still directly parseable as a registered subcommand.
    assert flat in EXPECTED_CLI_COMMANDS


def test_qa_group_keeps_exactly_five_aliases():
    """The T7c qa group is exactly its five known aliases (auto-chapters, info-detailed, check, design-check, fix-design)."""

    qa = {k: v for k, v in NAMESPACED_ALIASES.items() if k[0] == "qa"}
    assert qa == QA_ALIASES
    assert len(qa) == 5


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
    """The flat subcommand set is the same 130-command surface; no new parser was added.

    Namespace aliases are pure argv rewrites to existing flat commands, never new
    subcommands: 7 aivideo aliases (T7a) + 9 audio aliases (T7b) + 5 qa aliases
    (T7c) = 21 grouped paths over the unchanged 130-command parser.
    """

    assert len(EXPECTED_CLI_COMMANDS) == 130
    assert len(NAMESPACED_ALIASES) == 21
    groups = namespaced_groups()
    assert set(groups) == {"aivideo", "audio", "qa"}
    assert groups["aivideo"] == (
        "acceptance",
        "body-swap",
        "ingest",
        "inspect",
        "preflight",
        "salvage",
        "verdict",
    )
    assert groups["audio"] == (
        "add-generated",
        "bed",
        "compose",
        "effects",
        "normalize",
        "preset",
        "sequence",
        "spatial",
        "synthesize",
    )
    assert groups["qa"] == (
        "auto-chapters",
        "check",
        "design-check",
        "fix-design",
        "info-detailed",
    )


def test_parser_does_not_register_a_namespace_group_subparser():
    """Grouped routing reuses flat subparsers; no `aivideo`, `audio`, or `qa` subparser is created."""

    import argparse as _argparse

    parser = build_parser()
    subparsers_action = next(action for action in parser._actions if isinstance(action, _argparse._SubParsersAction))
    choices = set(subparsers_action.choices)
    assert "aivideo" not in choices
    assert "audio" not in choices
    assert "qa" not in choices
    assert choices == EXPECTED_CLI_COMMANDS


def test_grouped_route_exposes_target_help():
    """`kino aivideo verdict --help` rewrites so argparse prints the flat command's help."""

    result = _cli("aivideo", "verdict", "--help")
    assert result.returncode == 0, result.stderr
    # The flat command's help is shown — its prog line and required positional appear verbatim.
    assert "video-verdict" in result.stdout
    assert "--verdict-json" in result.stdout


def test_grouped_audio_bed_route_exposes_flat_audio_bed_help():
    """`kino audio bed --help` rewrites so argparse prints the flat audio-bed command's help."""

    result = _cli("audio", "bed", "--help")
    assert result.returncode == 0, result.stderr
    # The flat audio-bed command's help is shown — its prog line and a distinctive option appear verbatim.
    assert "audio-bed" in result.stdout
    assert "--loop-crossfade" in result.stdout


def test_grouped_qa_check_route_exposes_flat_video_quality_check_help():
    """`kino qa check --help` rewrites so argparse prints the flat video-quality-check command's help."""

    result = _cli("qa", "check", "--help")
    assert result.returncode == 0, result.stderr
    # The flat video-quality-check command's help is shown — its prog line and a distinctive option appear verbatim.
    assert "video-quality-check" in result.stdout
    assert "--fail-on-warning" in result.stdout


def test_group_help_does_not_add_namespace_groups_to_top_level_command_list():
    """`kino --help` still lists exactly the flat 130 commands — no aivideo, audio, or qa entry."""

    result = _cli("--help")
    assert result.returncode == 0, result.stderr
    command_lists = re.findall(r"\{([^}]+)\}", result.stdout)
    command_list = max(command_lists, key=lambda value: len(value.split(",")))
    help_commands = set(command_list.split(","))
    assert help_commands == EXPECTED_CLI_COMMANDS
    assert "aivideo" not in help_commands
    assert "audio" not in help_commands
    assert "qa" not in help_commands
