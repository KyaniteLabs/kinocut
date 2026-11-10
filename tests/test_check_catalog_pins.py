"""Offline checks for scripts/check_catalog_pins.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_catalog_pins.py"
_spec = importlib.util.spec_from_file_location("check_catalog_pins", _PATH)
pins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins)


def _run(monkeypatch, catalog_text: str, latest: str) -> int:
    monkeypatch.setattr(pins, "_get", lambda url: catalog_text)
    return pins.main(["--latest", latest])


def test_finds_every_pin_in_a_listing():
    text = 'description: "launches uvx kinocut==1.16.4"\nargs: ["kinocut==1.16.4"]'
    assert pins.pins_in(text) == {"1.16.4"}


def test_older_catalog_pin_fails(monkeypatch, capsys):
    assert _run(monkeypatch, "uvx kinocut==1.16.4", "2.0.0") == 1
    assert "launches kinocut==1.16.4; latest is 2.0.0" in capsys.readouterr().out


def test_versions_compare_numerically_not_as_text(monkeypatch):
    assert pins._key("1.16.10") > pins._key("1.16.9")
    assert pins._key("2.0.0") > pins._key("1.16.8")


def test_listing_with_no_pin_fails(monkeypatch, capsys):
    assert _run(monkeypatch, "command: kinocut", "0.0.1") == 1
    assert "no kinocut== pin found" in capsys.readouterr().out
