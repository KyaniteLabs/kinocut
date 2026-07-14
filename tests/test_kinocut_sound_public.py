"""S12 public parity discovery and thin adapter tests."""

from __future__ import annotations
import json
from kinocut_sound.public import (
    discover_sound_capabilities,
    invoke_sound_operation,
    list_flat_commands,
    list_namespaced_commands,
)


def test_flat_and_namespaced_parity_same_operations():
    flat = list_flat_commands()
    ns = list_namespaced_commands()
    assert len(flat) == len(ns)
    # same operation stems
    flat_ops = {c.removeprefix("sound-") for c in flat}
    ns_ops = {c.removeprefix("sound.").replace(".", "-") for c in ns}
    assert flat_ops == ns_ops


def test_capability_manifest_local_first_json_safe():
    m = discover_sound_capabilities()
    assert m.local_first is True
    assert m.non_tty_json is True
    payload = {
        "capabilities": list(m.capabilities),
        "flat": list(m.flat_commands),
        "ns": list(m.namespaced_commands),
    }
    # JSON serializable, no absolute paths
    text = json.dumps(payload)
    assert "/home/" not in text
    assert "password" not in text.lower()


def test_invoke_capabilities_and_qa():
    caps = invoke_sound_operation("sound-capabilities")
    assert "voice_local" in caps["capabilities"]
    assert caps["non_tty_json"] is True
    loud = invoke_sound_operation("sound.qa.loudness")
    assert loud["within_tolerance"] is True
    mix = invoke_sound_operation("sound-mix-render")
    assert mix["within_tolerance"] is True


def test_unknown_operation_raises():
    import pytest

    with pytest.raises(KeyError):
        invoke_sound_operation("sound-does-not-exist")
