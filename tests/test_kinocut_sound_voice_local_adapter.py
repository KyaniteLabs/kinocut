"""Local TTS adapter tests for the S5 voice leaf.

Covers the local-first adapter surface:

* Probe returns ``available=True``; descriptor is statically code-owned and
  local-locality.
* ``render`` produces a deterministic WAV: same inputs -> same bytes/hash.
* Prosody overrides change the rendered signal measurably (duration for
  rate, base frequency for pitch, gain for volume).
* Emotion direction changes the rendered signal.
* A pronunciation override changes rendering for a matching term hash.
* The cloud-only stub returns unavailable without network activity and
  refuses to render.
* Hostile/lying inputs fail closed with bounded errors.
* No private marker, local path, credential, or raw provider error leaks
  through the public surface.
"""

from __future__ import annotations

import struct

import pytest

from kinocut_sound import (
    AdapterLocality,
    Emotion,
    Line,
    PronunciationOverride,
    ProfileRef,
    Prosody,
)
from kinocut_sound.voice import (
    ADAPTER_INPUT_INVALID,
    CLOUD_NOT_ALLOWED,
    CloudTtsAdapterStub,
    LocalSynthesisAdapter,
    PronunciationDictionary,
    SynthesisOutput,
    TtsAdapter,
    VoiceError,
    cloud_allowed,
    cloud_descriptor,
    default_roster,
    dictionary_fingerprint,
)


def _line(
    *,
    prosody: Prosody | None = None,
    emotion: Emotion | None = None,
    overrides: tuple[PronunciationOverride, ...] = (),
    text_hash: str = "sha256:" + "a" * 64,
    text_length_chars: int = 24,
    line_id: str = "line_1",
) -> Line:
    return Line(
        line_id=line_id,
        character_id="hero",
        profile=ProfileRef(profile_id="hero_tenor", version=1),
        text_hash=text_hash,
        text_length_chars=text_length_chars,
        prosody=prosody or Prosody(),
        emotion=emotion or Emotion(label="neutral", intensity=0.0),
        spatial_preset="medium_room",
        pronunciation_overrides=overrides,
        inherit_loudness=True,
    )


def test_local_adapter_conforms_to_tts_protocol_and_probe_available():
    adapter = LocalSynthesisAdapter()
    assert isinstance(adapter, TtsAdapter)
    descriptor = adapter.descriptor
    assert descriptor.adapter_id == "tts_local_synth"
    assert descriptor.kind == "tts"
    assert descriptor.locality is AdapterLocality.LOCAL
    assert descriptor.cost_disclosure is None
    probe = adapter.probe()
    assert probe.available is True
    assert probe.reason_code is None
    assert probe.remediation is None


def test_render_returns_synthesis_output_with_wav_bytes_and_hash():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    out = adapter.render(slot=slot, line=_line())
    assert isinstance(out, SynthesisOutput)
    assert out.output_hash.startswith("sha256:")
    assert len(out.output_hash) == 71
    assert out.sample_rate_hz == adapter.sample_rate_hz
    assert out.channel_count == 1
    assert out.duration_seconds > 0
    # WAV header: 'RIFF', size, 'WAVE', 'fmt ', chunk size 16, format=1 (PCM).
    assert out.wav_bytes[:4] == b"RIFF"
    assert out.wav_bytes[8:12] == b"WAVE"
    assert out.wav_bytes[12:16] == b"fmt "
    (fmt_chunk_size,) = struct.unpack_from("<I", out.wav_bytes, 16)
    assert fmt_chunk_size == 16
    (audio_format,) = struct.unpack_from("<H", out.wav_bytes, 20)
    assert audio_format == 1


def test_render_is_byte_deterministic_across_identical_inputs():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    out_a = adapter.render(slot=slot, line=_line())
    out_b = adapter.render(slot=slot, line=_line())
    assert out_a.wav_bytes == out_b.wav_bytes
    assert out_a.output_hash == out_b.output_hash
    assert out_a.recipe_digest == out_b.recipe_digest


def test_distinct_text_hashes_produce_distinct_outputs():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    out_a = adapter.render(slot=slot, line=_line(text_hash="sha256:" + "a" * 64))
    out_b = adapter.render(slot=slot, line=_line(text_hash="sha256:" + "b" * 64))
    assert out_a.output_hash != out_b.output_hash


def test_prosody_rate_change_changes_duration_and_signal():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    # ``android_neutral`` has a neutral base rate of 1.0 so composed rates
    # stay inside the design envelope (slot rate * prosody rate <= 2.0).
    slot = roster.get("android_neutral")
    slow = adapter.render(slot=slot, line=_line(prosody=Prosody(rate=0.5)))
    fast = adapter.render(slot=slot, line=_line(prosody=Prosody(rate=1.5)))
    assert slow.duration_seconds > fast.duration_seconds
    assert slow.output_hash != fast.output_hash


def test_prosody_pitch_change_changes_signal_measurably():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    low = adapter.render(slot=slot, line=_line(prosody=Prosody(pitch=-6.0)))
    high = adapter.render(slot=slot, line=_line(prosody=Prosody(pitch=6.0)))
    assert low.output_hash != high.output_hash
    # The base frequency shifts; the WAV bytes differ visibly.
    assert low.wav_bytes != high.wav_bytes


def test_prosody_volume_change_changes_signal_measurably():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    quiet = adapter.render(slot=slot, line=_line(prosody=Prosody(volume_db=-12.0)))
    loud = adapter.render(slot=slot, line=_line(prosody=Prosody(volume_db=0.0)))
    assert quiet.output_hash != loud.output_hash
    # Quiet signal's peak amplitude should be measurably smaller.
    quiet_peak = max(struct.unpack_from("<h", quiet.wav_bytes[44 + i * 2 :])[0] for i in range(0, 1000))
    loud_peak = max(struct.unpack_from("<h", loud.wav_bytes[44 + i * 2 :])[0] for i in range(0, 1000))
    assert quiet_peak < loud_peak


def test_emotion_direction_change_changes_rendered_signal():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    calm = adapter.render(slot=slot, line=_line(emotion=Emotion(label="calm", intensity=0.7)))
    joyful = adapter.render(slot=slot, line=_line(emotion=Emotion(label="joy", intensity=0.7)))
    fearful = adapter.render(slot=slot, line=_line(emotion=Emotion(label="fear", intensity=0.7)))
    assert calm.output_hash != joyful.output_hash
    assert calm.output_hash != fearful.output_hash
    assert joyful.output_hash != fearful.output_hash


def test_emotion_intensity_change_changes_rendered_signal():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    low = adapter.render(slot=slot, line=_line(emotion=Emotion(label="joy", intensity=0.1)))
    high = adapter.render(slot=slot, line=_line(emotion=Emotion(label="joy", intensity=1.0)))
    assert low.output_hash != high.output_hash


def test_distinct_roster_slots_produce_distinct_outputs():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    hero = roster.get("hero_tenor")
    villain = roster.get("villain_baritone")
    out_hero = adapter.render(slot=hero, line=_line())
    out_villain = adapter.render(slot=villain, line=_line())
    assert out_hero.output_hash != out_villain.output_hash


def test_pronunciation_override_changes_rendering_for_matching_term_hash():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    term_hash = "sha256:" + "c" * 64
    no_dict = adapter.render(slot=slot, line=_line())
    override = PronunciationOverride(term_hash=term_hash, ipa="ka.ton")
    dictionary = PronunciationDictionary({term_hash: override})
    with_override_line = _line(overrides=(override,))
    with_dict = adapter.render(slot=slot, line=with_override_line, dictionary=dictionary)
    assert no_dict.output_hash != with_dict.output_hash
    # Sanity: distinct dictionaries shift the output too.
    other_override = PronunciationOverride(term_hash=term_hash, ipa="other")
    other_dict = PronunciationDictionary({term_hash: other_override})
    other_line = _line(overrides=(other_override,))
    other = adapter.render(slot=slot, line=other_line, dictionary=other_dict)
    assert with_dict.output_hash != other.output_hash


def test_dictionary_fingerprint_is_stable_and_does_not_leak_raw_text():
    term_hash = "sha256:" + "d" * 64
    override = PronunciationOverride(term_hash=term_hash, ipa="ku.tu")
    dictionary = PronunciationDictionary({term_hash: override})
    fingerprint_a = dictionary_fingerprint(dictionary, _line())
    fingerprint_b = dictionary_fingerprint(dictionary, _line())
    assert fingerprint_a == fingerprint_b
    serialized = repr(fingerprint_a)
    assert "/home/" not in serialized
    assert "password" not in serialized.lower()


def test_dictionary_fingerprint_changes_with_distinct_overrides():
    term_hash = "sha256:" + "d" * 64
    base_line = _line()
    empty = dictionary_fingerprint(None, base_line)
    override = PronunciationOverride(term_hash=term_hash, ipa="ku.tu")
    with_override_line = _line(overrides=(override,))
    populated = dictionary_fingerprint(None, with_override_line)
    assert empty != populated


def test_cloud_descriptor_is_cloud_locality_with_unconfirmed_cost_disclosure():
    descriptor = cloud_descriptor()
    assert descriptor.locality is AdapterLocality.CLOUD
    assert descriptor.kind == "tts"
    assert descriptor.cost_disclosure is not None
    assert descriptor.cost_disclosure.confirmed is False
    assert descriptor.cost_disclosure.provider_id == "elevenlabs"
    assert descriptor.cost_disclosure.region == "us-east-1"


def test_cloud_stub_probe_returns_unavailable_with_bounded_reason():
    stub = CloudTtsAdapterStub()
    probe = stub.probe()
    assert probe.available is False
    assert probe.reason_code == CLOUD_NOT_ALLOWED
    # Remediation is bounded advisory: no host paths, URLs, or credentials.
    remediation = probe.remediation or ""
    assert "/home/" not in remediation
    assert "http" not in remediation
    assert "password" not in remediation.lower()


def test_cloud_stub_render_raises_without_network_activity(monkeypatch):
    # Defang any accidental socket use so a regression in the stub fails
    # the test loudly rather than reaching a network.
    import socket

    def _fail(*args, **kwargs):
        raise AssertionError("cloud stub attempted network activity")

    monkeypatch.setattr(socket, "socket", _fail)
    stub = CloudTtsAdapterStub()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    with pytest.raises(VoiceError) as exc:
        stub.render(slot=slot, line=_line())
    assert exc.value.code == CLOUD_NOT_ALLOWED
    # No leakage of host paths, provider internal errors, or credentials.
    msg = str(exc.value)
    assert "/home/" not in msg
    assert "api_key" not in msg.lower()
    assert " bearer " not in msg.lower()


def test_cloud_allowed_returns_false_without_explicit_opt_in():
    descriptor = cloud_descriptor()
    assert cloud_allowed(policy=None, descriptor=descriptor) is False
    assert cloud_allowed(policy={}, descriptor=descriptor) is False
    assert cloud_allowed(policy={"allow_cloud": True}, descriptor=descriptor) is False
    assert (
        cloud_allowed(
            policy={"allow_cloud": True, "cloud_approval": "tts_cloud_other"},
            descriptor=descriptor,
        )
        is False
    )
    assert (
        cloud_allowed(
            policy={"allow_cloud": "true", "cloud_approval": descriptor.adapter_id},
            descriptor=descriptor,
        )
        is False
    )


def test_cloud_allowed_returns_true_for_explicit_opt_in_matching_approval():
    descriptor = cloud_descriptor()
    assert (
        cloud_allowed(
            policy={"allow_cloud": True, "cloud_approval": descriptor.adapter_id},
            descriptor=descriptor,
        )
        is True
    )


def test_local_adapter_rejects_invalid_sample_rate_and_mono_only():
    with pytest.raises(VoiceError) as exc:
        LocalSynthesisAdapter(sample_rate_hz=0)
    assert exc.value.code == ADAPTER_INPUT_INVALID
    with pytest.raises(VoiceError):
        LocalSynthesisAdapter(sample_rate_hz=True)  # type: ignore[arg-type]
    with pytest.raises(VoiceError):
        LocalSynthesisAdapter(channel_count=2)


def test_render_does_not_leak_host_paths_credentials_or_provider_errors():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("hero_tenor")
    out = adapter.render(slot=slot, line=_line())
    serialized = repr(out.wav_bytes)
    assert "/home/" not in serialized
    assert "password" not in serialized.lower()
    # The descriptor's provider_class is bounded; no API key prose rides in.
    descriptor_repr = repr(adapter.descriptor.model_dump())
    assert "api_key" not in descriptor_repr.lower()


def test_render_is_signal_equivalent_deterministic_under_repeated_calls():
    adapter = LocalSynthesisAdapter()
    roster = default_roster()
    slot = roster.get("android_neutral")
    outputs = [adapter.render(slot=slot, line=_line()) for _ in range(5)]
    first_hash = outputs[0].output_hash
    assert all(o.output_hash == first_hash for o in outputs)
    assert all(o.wav_bytes == outputs[0].wav_bytes for o in outputs)
