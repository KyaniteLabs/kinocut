"""Offline tests for cutover --require-live."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.error import HTTPError

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_public_release_cutover.py"
_SPEC = importlib.util.spec_from_file_location("apply_public_release_cutover", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
cutover = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cutover)


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_live_pypi_has_version_true() -> None:
    assert cutover.live_pypi_has_version("1.14.1", opener=lambda req, timeout: _FakeResp(200))


def test_live_pypi_has_version_404() -> None:
    def opener(req, timeout):
        raise HTTPError("https://pypi.org/pypi/kinocut/1.15.0/json", 404, "Not Found", {}, None)

    assert cutover.live_pypi_has_version("1.15.0", opener=opener) is False


def test_require_live_blocks_missing_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cutover, "live_pypi_has_version", lambda version: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_public_release_cutover.py",
            "--version",
            "1.15.0",
            "--date",
            "2026-08-15",
            "--mcp-tools",
            "196",
            "--cli-commands",
            "167",
        ],
    )
    assert cutover.main() == 1
