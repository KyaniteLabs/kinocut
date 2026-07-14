"""S15 stop-gate smoke: privacy and non-release invariants."""

from __future__ import annotations

import json
from pathlib import Path

from kinocut_sound.public import discover_sound_capabilities, invoke_sound_operation


def test_public_payloads_have_no_host_paths_or_secrets():
    caps = invoke_sound_operation("sound-capabilities")
    text = json.dumps(caps)
    assert "/home/" not in text
    assert "api_key" not in text.lower()
    assert "password" not in text.lower()


def test_discovery_is_local_first():
    m = discover_sound_capabilities()
    assert m.local_first is True
    assert m.non_tty_json is True


def test_gate_receipt_declares_stop_before_release():
    receipt = Path("docs/status/2026-07-14-sound-s13-s15-gate-receipt.md")
    text = receipt.read_text(encoding="utf-8")
    assert "STOP before release" in text
    assert "NOT AUTHORIZED" in text
    assert "No version bump" in text
