"""Retry hints only name kino commands that really exist (#685)."""

from __future__ import annotations

import re

import pytest

from kinocut.errors import _cli_command_set, retry_context, retry_message
from kinocut.tool_registry import TOOL_REGISTRY

_KINO = re.compile(r"\bkino ([a-z0-9][a-z0-9-]*)")


def test_cli_command_set_is_real():
    assert len(_cli_command_set()) > 100


@pytest.mark.parametrize("code", ["invalid_parameter", "ffmpeg_not_found", "network_consent_required"])
def test_every_tool_hint_names_only_registered_kino_commands(code):
    commands = _cli_command_set()
    invented = {}
    for tool in TOOL_REGISTRY:
        with retry_context(tool):
            message = retry_message("boom", code)
        assert f"call {tool}" in message or "KINOCUT_HYPERFRAMES_TELEMETRY" in message
        for route in _KINO.findall(message):
            if route not in commands:
                invented[tool] = route
    assert not invented, f"retry hints name nonexistent kino commands: {sorted(invented.items())[:10]}"


def test_prefixed_command_keeps_its_prefix():
    with retry_context("sound_plan_validate"):
        message = retry_message("bad plan", "invalid_plan")
    assert "run kino sound-plan-validate with corrected flags (CLI)" in message


def test_mcp_only_tool_omits_cli_half():
    with retry_context("glitch_rgb_shift"):
        message = retry_message("bad", "invalid_parameter")
    assert message.endswith("; retry with call glitch_rgb_shift with corrected parameters (MCP)")
    assert "kino" not in message
