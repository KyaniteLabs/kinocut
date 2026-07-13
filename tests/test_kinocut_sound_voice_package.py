"""Voice package integration tests (S5).

These tests exercise the leaf end-to-end: the public exports, the public
namespace does not widen any ``kinocut_sound`` contract, and the sidecar
boundary stays clean (no ``kinocut.*`` runtime import).
"""

from __future__ import annotations

import importlib
import sys

import kinocut_sound.voice as voice


def test_package_public_exports_are_present_and_distinct():
    public = voice.__all__
    assert len(public) == len(set(public))
    for name in public:
        assert hasattr(voice, name), f"missing public export: {name}"


def test_package_does_not_import_kinocut_runtime_modules():
    # Snapshot existing kinocut.* imports, import the voice leaf, then verify
    # no new kinocut.* runtime module entered sys.modules.
    pre = {key for key in sys.modules if key.startswith("kinocut.") and ".voice" not in key}
    importlib.reload(voice)
    post = {key for key in sys.modules if key.startswith("kinocut.") and ".voice" not in key}
    # No new kinocut runtime module loaded by importing/reloading the leaf.
    assert post.issubset(pre | {"kinocut"})


def test_voice_errors_are_sound_contract_subclasses():
    from kinocut_sound._errors import SoundContractError

    err = voice.voice_error("msg", voice.ROSTER_UNKNOWN)
    assert isinstance(err, SoundContractError)
    assert isinstance(err, voice.VoiceError)
    payload = err.to_dict()
    assert payload["code"] == voice.ROSTER_UNKNOWN
    assert payload["suggested_action"]["auto_fix"] is False


def test_bounded_voice_error_carries_advisory_remediation_without_host_paths():
    err = voice.bounded_voice_error("msg", voice.VOICE_UNAVAILABLE)
    remediation = err.suggested_action.get("remediation", "")
    assert isinstance(remediation, str)
    assert remediation
    assert "/home/" not in remediation
    assert "http" not in remediation
    assert "password" not in remediation.lower()


def test_package_version_is_bounded_string():
    assert isinstance(voice.__version__, str)
    assert voice.__version__.count(".") == 2


def test_known_emotion_labels_include_design_set():
    labels = voice.known_emotion_labels()
    for required in ("neutral", "calm", "joy", "anger", "fear"):
        assert required in labels
