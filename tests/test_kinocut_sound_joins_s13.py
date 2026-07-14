"""S13 host-join tests: real D41/D42 bindings under kinocut.sound_joins."""

from __future__ import annotations

import json

from kinocut.sound_joins import (
    D41_BED_KINOCUT_ADAPTER_ID,
    D42_STYLE_KINOCUT_ADAPTER_ID,
    KinocutD41Port,
    KinocutD42Port,
    default_kinocut_d41_port,
    default_kinocut_d42_port,
)
from kinocut_sound.voice_consistency.d42_port import (
    IdentityCheckSpec,
    StyleCheckSpec,
)
from kinocut_sound.voice_consistency.metrics import identity_similarity, style_check
from kinocut_sound.world.d41_port import (
    AuditionPort,
    BedKind,
    BedPort,
    BedSpec,
)

_SHA = "sha256:" + "a" * 64
_SHA2 = "sha256:" + "c" * 64


def test_kinocut_d41_port_probes_and_conforms():
    port = default_kinocut_d41_port()
    assert isinstance(port, KinocutD41Port)
    assert isinstance(port.bed, BedPort)
    assert isinstance(port.audition, AuditionPort)
    bed_p, aud_p = port.probe()
    assert bed_p.available is True
    assert aud_p.available is True
    assert port.bed.descriptor.adapter_id == D41_BED_KINOCUT_ADAPTER_ID


def test_kinocut_d41_prepare_bed_stamps_real_adapter():
    port = default_kinocut_d41_port()
    desc = port.bed.prepare_bed(
        BedSpec(
            bed_id="bed_common_room",
            kind=BedKind.AMBIENT_BED,
            description_hash=_SHA,
            duration_seconds=30.0,
        )
    )
    assert desc.bed_id == "bed_common_room"
    assert desc.descriptor_hash.startswith("sha256:")
    # Deterministic
    desc2 = port.bed.prepare_bed(
        BedSpec(
            bed_id="bed_common_room",
            kind=BedKind.AMBIENT_BED,
            description_hash=_SHA,
            duration_seconds=30.0,
        )
    )
    assert desc.descriptor_hash == desc2.descriptor_hash
    text = desc.descriptor_hash + desc.bed_id
    for forbidden in ("/home/", "/etc/", "password", "api_key"):
        assert forbidden not in text


def test_kinocut_d41_audition_always_human_review():
    port = default_kinocut_d41_port()
    reel = port.audition.build_audition_reel(
        bed_id="bed_common_room",
        reel_label="reel_001",
        description_hash=_SHA,
    )
    assert reel.human_review_required is True
    assert reel.reel_hash.startswith("sha256:")


def test_kinocut_d42_port_probes_and_style_check():
    port = default_kinocut_d42_port()
    assert isinstance(port, KinocutD42Port)
    s, i = port.probe()
    assert s.available is True
    assert i.available is True
    assert port.style.descriptor.adapter_id == D42_STYLE_KINOCUT_ADAPTER_ID
    result = port.style.check_style(
        StyleCheckSpec(
            profile_id="narrator_main",
            audio_hash=_SHA,
            reference_hash=_SHA,
        )
    )
    assert result.similarity == 1.0
    assert result.drift is False
    result2 = port.style.check_style(
        StyleCheckSpec(
            profile_id="narrator_main",
            audio_hash=_SHA,
            reference_hash=_SHA2,
        )
    )
    assert 0.0 <= result2.similarity <= 1.0
    assert "assets_unresolved" in result2.flags


def test_kinocut_d42_identity_and_metrics_facade():
    port = default_kinocut_d42_port()
    ident = port.identity.compare_identity(IdentityCheckSpec(audio_hash_a=_SHA, audio_hash_b=_SHA))
    assert ident.same_identity is True
    assert ident.similarity == 1.0
    # metrics helpers accept the host port facade (duck-typed)
    metrics = style_check(
        port=port,  # type: ignore[arg-type]
        profile_id="narrator_main",
        audio_hash=_SHA,
        reference_hash=_SHA,
    )
    assert metrics.similarity == 1.0
    assert metrics.drift is False
    sim = identity_similarity(
        port=port,  # type: ignore[arg-type]
        audio_hash_a=_SHA,
        audio_hash_b=_SHA2,
    )
    assert 0.0 <= sim <= 1.0


def test_host_join_payloads_have_no_leaks():
    port = default_kinocut_d41_port()
    d42 = default_kinocut_d42_port()
    payload = {
        "d41": [p.adapter_id for p in port.probe()],
        "d42": [p.adapter_id for p in d42.probe()],
    }
    text = json.dumps(payload)
    assert "/home/" not in text
    assert "password" not in text.lower()
