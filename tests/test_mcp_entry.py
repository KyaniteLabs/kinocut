"""MCP-mode entry error honesty (#448, second half of #445).

A broad ``except ImportError`` used to report every server-tree import failure
as a missing ``mcp`` package. These tests pin the two failure classes: the
genuine absence of ``mcp`` keeps the install hint; anything else surfaces its
real cause.
"""

from __future__ import annotations

import pytest

import kinocut.__main__ as entry


class _Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **_kwargs: object) -> None:
        self.lines.append("".join(str(arg) for arg in args))


@pytest.fixture()
def printed(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(entry.err_console, "print", recorder)
    return recorder


def test_missing_mcp_package_keeps_install_hint(printed: _Recorder) -> None:
    def _boom() -> None:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    with pytest.raises(SystemExit) as excinfo:
        entry._run_mcp_mode(import_server=_boom)
    assert excinfo.value.code == 1
    assert any("MCP mode requires the 'mcp' package" in line for line in printed.lines)


def test_missing_mcp_submodule_keeps_install_hint(printed: _Recorder) -> None:
    def _boom() -> None:
        raise ModuleNotFoundError("No module named 'mcp.server'", name="mcp.server")

    with pytest.raises(SystemExit):
        entry._run_mcp_mode(import_server=_boom)
    assert any("MCP mode requires the 'mcp' package" in line for line in printed.lines)


def test_other_missing_module_surfaces_real_error(printed: _Recorder) -> None:
    """The #445 scenario: a POSIX-only module fails to import on Windows."""

    def _boom() -> None:
        raise ModuleNotFoundError("No module named 'fcntl'", name="fcntl")

    with pytest.raises(SystemExit) as excinfo:
        entry._run_mcp_mode(import_server=_boom)
    assert excinfo.value.code == 1
    assert any("MCP mode failed to start" in line and "fcntl" in line for line in printed.lines)
    assert not any("requires the 'mcp' package" in line for line in printed.lines)


def test_nameless_import_error_surfaces_real_error(printed: _Recorder) -> None:
    def _boom() -> None:
        raise ImportError("cannot import name 'tool' from 'kinocut.server'")

    with pytest.raises(SystemExit) as excinfo:
        entry._run_mcp_mode(import_server=_boom)
    assert excinfo.value.code == 1
    assert any("MCP mode failed to start" in line and "cannot import name" in line for line in printed.lines)


def test_non_import_errors_from_server_propagate() -> None:
    class _Server:
        def run(self) -> None:
            raise RuntimeError("server crashed")

    with pytest.raises(RuntimeError, match="server crashed"):
        entry._run_mcp_mode(import_server=_Server)


def test_main_dispatches_mcp_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(entry, "_run_mcp_mode", lambda: calls.append(1))
    monkeypatch.setattr("sys.argv", ["kino", "--mcp"])
    entry.main()
    assert calls == [1]


def test_plain_import_error_with_mcp_name_surfaces_real_error(printed: _Recorder) -> None:
    """Only ModuleNotFoundError means absence; a crafted ImportError('name=mcp') does not."""

    def _boom() -> None:
        raise ImportError("custom import failure", name="mcp")

    with pytest.raises(SystemExit):
        entry._run_mcp_mode(import_server=_boom)
    assert any("MCP mode failed to start" in line for line in printed.lines)
    assert not any("requires the 'mcp' package" in line for line in printed.lines)


def test_path_bearing_import_error_is_redacted(printed: _Recorder) -> None:
    def _boom() -> None:
        raise ImportError("cannot load /Users/secret/codec/lib.py on this platform")

    with pytest.raises(SystemExit):
        entry._run_mcp_mode(import_server=_boom)
    joined = "\n".join(printed.lines)
    assert "/Users/secret" not in joined
    assert "[path]" in joined


def test_markup_in_import_error_is_neutralized(printed: _Recorder) -> None:
    def _boom() -> None:
        raise ImportError("use [bold]red[/bold] tags carefully")

    with pytest.raises(SystemExit):
        entry._run_mcp_mode(import_server=_boom)
    joined = "\n".join(printed.lines)
    assert "[bold]red[/bold]" not in joined  # escaped to literal \[bold]...
