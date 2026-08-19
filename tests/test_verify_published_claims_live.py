"""Offline tests for the live published-claims probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_published_claims_live.py"
_SPEC = importlib.util.spec_from_file_location("verify_published_claims_live", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
live = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(live)
load_claimed_published = live.load_claimed_published
main = live.main
pypi_latest = live.pypi_latest


def test_load_claimed_published_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "public_claims.json"
    path.write_text(json.dumps({"published_version": "1.14.1"}), encoding="utf-8")
    assert load_claimed_published(path) == "1.14.1"


def test_pypi_latest_red_on_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    claims = tmp_path / "public_claims.json"
    claims.write_text(json.dumps({"published_version": "1.15.0"}), encoding="utf-8")

    def fake_get_json(url: str):
        if "pypi.org" in url:
            return 200, {"info": {"version": "1.14.1"}}, ""
        if "npmjs.org" in url:
            return 200, {"version": "1.14.1"}, ""
        if "releases/latest" in url:
            return 200, {"tag_name": "v1.14.1"}, ""
        return 0, None, "unexpected"

    monkeypatch.setattr(live, "_get_json", fake_get_json)
    assert main(["--claims", str(claims)]) == 1


def test_pypi_latest_green_when_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    claims = tmp_path / "public_claims.json"
    claims.write_text(json.dumps({"published_version": "1.14.1"}), encoding="utf-8")

    def fake_get_json(url: str):
        if "pypi.org" in url:
            return 200, {"info": {"version": "1.14.1"}}, ""
        if "npmjs.org" in url:
            return 200, {"version": "9.9.9"}, ""
        if "releases/latest" in url:
            return 200, {"tag_name": "v9.9.9"}, ""
        return 0, None, "unexpected"

    monkeypatch.setattr(live, "_get_json", fake_get_json)
    assert main(["--claims", str(claims)]) == 0


def test_pypi_probe_network_error_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        live,
        "_get_json",
        lambda url: (0, None, "timed out") if "pypi.org" in url else (200, {"version": "1"}, ""),
    )
    version, err = pypi_latest()
    assert version is None
    assert "timed out" in err
