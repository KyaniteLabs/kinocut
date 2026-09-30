"""S13 host-join contracts and truthful semantic voice capability status."""

from __future__ import annotations

import json
import shutil

import pytest

from kinocut.errors import MCPVideoError
from kinocut.sound_joins.d42_bind import PathAssetIndex
from kinocut_sound.voice_consistency._errors import VoiceConsistencyError

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


def test_kinocut_d42_ports_do_not_claim_ffmpeg_is_a_perceptual_backend(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda executable: f"/fake/bin/{executable}")
    port = default_kinocut_d42_port()
    assert isinstance(port, KinocutD42Port)
    style, identity = port.probe()
    assert style.available is False
    assert identity.available is False
    assert style.reason_code == identity.reason_code == "d42_voice_seam_unavailable"
    assert "calibrated" in style.remediation
    assert "calibrated" in identity.remediation
    assert port.style.descriptor.adapter_id == D42_STYLE_KINOCUT_ADAPTER_ID


@pytest.mark.parametrize("reference", [_SHA, _SHA2])
@pytest.mark.parametrize("registered", [False, True])
def test_host_voice_ports_never_certify_hash_equality_or_invent_scores(tmp_path, reference, registered):
    assets = PathAssetIndex()
    if registered:
        audio = tmp_path / "unassessed.wav"
        audio.write_bytes(b"not a measured voice")
        assets.register(_SHA, str(audio))
        assets.register(reference, str(audio))
    port = default_kinocut_d42_port(assets)
    calls = [
        lambda: port.style.check_style(
            StyleCheckSpec(
                profile_id="narrator_main",
                audio_hash=_SHA,
                reference_hash=reference,
            )
        ),
        lambda: port.identity.compare_identity(IdentityCheckSpec(audio_hash_a=_SHA, audio_hash_b=reference)),
    ]
    for call in calls:
        with pytest.raises(MCPVideoError) as failure:
            call()
        assert failure.value.error_type == "dependency_error"
        assert failure.value.code == "d42_voice_seam_unavailable"
        assert failure.value.suggested_action["auto_fix"] is False
        if registered:
            assert str(audio) not in str(failure.value)


def test_kinocut_d42_metrics_facade_reports_unavailability():
    port = default_kinocut_d42_port()
    with pytest.raises(VoiceConsistencyError) as failure:
        style_check(
            port=port,  # type: ignore[arg-type]
            profile_id="narrator_main",
            audio_hash=_SHA,
            reference_hash=_SHA,
        )
    assert failure.value.code == "consistency_d42_unavailable"
    with pytest.raises(VoiceConsistencyError) as failure:
        identity_similarity(
            port=port,  # type: ignore[arg-type]
            audio_hash_a=_SHA,
            audio_hash_b=_SHA2,
        )
    assert failure.value.code == "consistency_d42_unavailable"


def test_path_asset_index_still_registers_actual_streamed_file_digest(tmp_path):
    import hashlib

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"preserved index bytes")
    assets = PathAssetIndex()
    digest = assets.register_file(str(audio))
    assert digest == "sha256:" + hashlib.sha256(audio.read_bytes()).hexdigest()
    assert assets.resolve(digest) == str(audio)


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
