"""S12 public parity discovery and thin adapter tests."""

from __future__ import annotations

import json

import pytest

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
    text = json.dumps(payload)
    assert "/home/" not in text
    assert "password" not in text.lower()


def test_invoke_all_discovered_operations():
    for name in list_flat_commands():
        result = invoke_sound_operation(name)
        assert isinstance(result, dict)
        text = json.dumps(result)
        assert "/Users/" not in text
        assert "/home/" not in text

    caps = invoke_sound_operation("sound-capabilities")
    assert "voice_local" in caps["capabilities"]
    assert caps["non_tty_json"] is True

    plan = invoke_sound_operation("sound.plan.validate")
    assert plan["ok"] is True
    assert plan["line_count"] >= 1
    assert plan["plan_hash"].startswith("sha256:")

    voice = invoke_sound_operation("sound-voice-batch")
    assert voice["ok"] is True
    assert voice["clip_count"] >= 1
    assert all(not c["output_path"].startswith("/") for c in voice["clips"])

    mix = invoke_sound_operation("sound-mix-render")
    assert mix["within_tolerance"] is True

    loud = invoke_sound_operation("sound.qa.loudness")
    assert loud["within_tolerance"] is True

    asr = invoke_sound_operation("sound-qa-asr")
    assert asr["ok"] is True
    assert asr["mismatch_count"] == 0


def test_plan_validate_rejects_hostile_payload():
    with pytest.raises(ValueError, match="sound plan validation failed"):
        invoke_sound_operation(
            "sound-plan-validate",
            plan={"project_id": 123, "not_a_plan": True},
        )


def test_unknown_operation_raises():
    with pytest.raises(KeyError):
        invoke_sound_operation("sound-does-not-exist")


def test_namespaced_and_flat_invoke_equivalent():
    flat = invoke_sound_operation("sound-capabilities")
    dotted = invoke_sound_operation("sound.capabilities")
    assert flat == dotted
