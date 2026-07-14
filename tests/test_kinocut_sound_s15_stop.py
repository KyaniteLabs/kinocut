"""S15 stop-gate smoke: privacy and non-release invariants for public adapters."""
from __future__ import annotations
import json
from kinocut_sound.public import invoke_sound_operation, discover_sound_capabilities

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
