"""No caller-controlled string reaches a public error message.

A refusal names the argument and the failure. It never repeats what the
caller passed: that string can be a path, a codec name, or a
credential-shaped token, and it must not travel back out to the caller.

A number is not a secret, and the operator needs it to correct the call, so
a number is repeated. Everything else — a string, a path, the text of a
caught exception — is the caller's own data and is named by type only.

This guard checks the *public* surface: the code an MCP tool handler can
reach. A refusal raised anywhere on that path is returned to the caller in
the JSON payload and rendered in the CLI panel, so a value that reaches one
of those messages has reached the caller.

The analysis lives in :mod:`tests.error_value_analysis` so that this guard
and the repair that fixed the leaks it reports agree on what a leak is.
"""

from __future__ import annotations

import ast

import pytest

from tests.error_value_analysis import (
    ROOT,
    find_leaks,
)


def test_no_caller_controlled_string_reaches_a_public_error_message() -> None:
    """The public surface names the argument and the failure, never the value."""
    violations = [
        f"{finding.path.relative_to(ROOT).as_posix()}:{finding.lineno}: {finding.source}" for finding in find_leaks()
    ]
    assert not violations, (
        "A caller-controlled string reaches a public error message.\n"
        "Describe the value by type (kinocut.validation_errors.rejected_value) "
        "instead of interpolating it.\n" + "\n".join(sorted(violations))
    )


def test_no_exemption_is_stale() -> None:
    """An exemption that matches nothing is a claim about code that has changed.

    The exemption list says a specific message is not caller data. If that
    message moves or changes, the exemption stops matching and the finding
    comes back, so a leftover entry is a false statement.
    """
    from tests.error_value_analysis import raw_leaks, unused_exemptions

    stale = unused_exemptions(raw_leaks())
    assert not stale, f"exemptions that no longer match anything: {stale}"


def test_the_guard_itself_detects_a_leak() -> None:
    """The guard is only worth shipping if it can fail."""
    from tests.error_value_analysis import Function, _is_tainted_expr

    probe = ast.parse("def handler(value):\n    pass\n").body[0]
    assert isinstance(probe, ast.FunctionDef)
    function = Function(ROOT / "probe.py", probe)
    function.tainted.add("value")

    leak = ast.parse("f'bad value: {value}'").body[0]
    assert isinstance(leak, ast.Expr)
    joined = leak.value
    assert isinstance(joined, ast.JoinedStr)
    fields = [part for part in joined.values if isinstance(part, ast.FormattedValue)]
    assert len(fields) == 1
    assert _is_tainted_expr(fields[0].value, function)

    safe = ast.parse("f'bad value: {rejected_value(value)}'").body[0]
    assert isinstance(safe, ast.Expr)
    safe_joined = safe.value
    assert isinstance(safe_joined, ast.JoinedStr)
    safe_fields = [part for part in safe_joined.values if isinstance(part, ast.FormattedValue)]
    assert len(safe_fields) == 1
    assert not _is_tainted_expr(safe_fields[0].value, function)


def test_a_number_is_still_reported_to_the_operator() -> None:
    """A number is not a secret, and the operator needs it to correct the call."""
    from kinocut.validation_errors import rejected_value

    assert rejected_value(30) == "30"
    assert rejected_value(2.5) == "2.5"
    assert rejected_value(True) == "bool"
    assert rejected_value("sk-secret") == "str"
    assert rejected_value(["sk-secret"]) == "list"


def test_an_exception_is_reported_by_kind_and_never_by_its_text() -> None:
    """An exception's text embeds the path that failed, so only its kind is kept."""
    from kinocut.validation_errors import exception_kind

    failure = OSError("No such file or directory: '/secret/9f3a7c.mp4'")
    assert exception_kind(failure) == "OSError"
    assert "9f3a7c" not in exception_kind(failure)


def test_our_own_reason_survives_but_a_foreign_one_does_not() -> None:
    """A refusal must not throw away the reason it gives.

    Our own error text was written under the value-free rule, so it is
    safe to publish again. A foreign exception's text embeds the path
    that failed, so only its kind is published.
    """
    from kinocut.errors import MCPVideoError
    from kinocut.validation_errors import reason

    ours = MCPVideoError("Unknown preset. Available: ['a', 'b']")
    assert reason(ours) == "Unknown preset. Available: ['a', 'b']"

    foreign = OSError("No such file or directory: '/secret/9f3a7c.mp4'")
    assert reason(foreign) == "OSError"
    assert "9f3a7c" not in reason(foreign)


def test_the_sound_package_keeps_its_reason_on_the_same_rule() -> None:
    """The sound package is independent, so it carries its own helper."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound._validation_errors import reason

    contract = SoundContractError("voice.overlap_seconds must be between 0 and 1", code="invalid_parameter")
    assert "voice.overlap_seconds" in reason(contract)

    foreign = OSError("No such file or directory: '/secret/9f3a7c.wav'")
    assert reason(foreign) == "OSError"
    assert "9f3a7c" not in reason(foreign)


@pytest.mark.parametrize("name", ["rejected_value", "exception_kind", "invalid_parameter", "reason"])
def test_the_shared_helper_exports_its_contract(name: str) -> None:
    import kinocut.validation_errors as module

    assert callable(getattr(module, name))
