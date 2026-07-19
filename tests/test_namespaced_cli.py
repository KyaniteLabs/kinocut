"""Namespaced CLI alias resolver (#52)."""

from __future__ import annotations

from tests.test_public_surface import EXPECTED_CLI_COMMANDS

from kinocut.cli.namespaces import NAMESPACED_ALIASES, namespaced_groups, resolve_namespaced


def test_resolve_returns_the_flat_command_for_a_namespaced_path():
    assert resolve_namespaced("aivideo", "verdict") == "video-verdict"
    assert resolve_namespaced("aivideo", "body-swap") == "video-body-swap"


def test_resolve_returns_none_for_an_unknown_path():
    assert resolve_namespaced("aivideo", "nope") is None
    assert resolve_namespaced("unknown", "verdict") is None


def test_every_alias_targets_a_registered_flat_command():
    for (group, action), flat in NAMESPACED_ALIASES.items():
        assert isinstance(flat, str) and flat in EXPECTED_CLI_COMMANDS, (group, action, flat)


def test_namespaced_groups_lists_actions_per_group():
    groups = namespaced_groups()
    assert "aivideo" in groups
    assert "verdict" in groups["aivideo"]
    # actions are sorted and unique within a group
    for actions in groups.values():
        assert list(actions) == sorted(actions)
        assert len(actions) == len(set(actions))
