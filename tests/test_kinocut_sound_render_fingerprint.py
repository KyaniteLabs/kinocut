"""RED-first tests for the ``kinocut_sound`` render fingerprint contract.

A render fingerprint covers the normalized SoundPlan, every byte hash, every
version vector, the codec/mux/conversion settings, the seed, locale,
hardware/backend, the concurrency ordering policy, and the required-capability
manifest. Its hash plus the stage/cue id forms the cache key. A determinism
class declares what replay guarantee the render provides.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.render_fingerprint import (
    DeterminismClass,
    FingerprintComponent,
    RenderFingerprint,
    ToolchainVersion,
)
from kinocut_sound.validation import DETERMINISM_CLASSES


_SHA = "sha256:" + "0" * 64


def test_determinism_classes_are_closed():
    assert frozenset({"byte_deterministic", "signal_equivalent", "non_reproducible"}) == DETERMINISM_CLASSES
    assert {d.value for d in DeterminismClass} == {
        "byte_deterministic",
        "signal_equivalent",
        "non_reproducible",
    }


def test_toolchain_version_rejects_unbounded_codes():
    ToolchainVersion(component="ffmpeg", version="6.0")
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            ToolchainVersion(component=bad, version="6.0")


def test_fingerprint_component_rejects_unbounded_codes_and_requires_hash():
    FingerprintComponent(role="plan_normalized", digest=_SHA)
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            FingerprintComponent(role=bad, digest=_SHA)


def test_render_fingerprint_cache_key_is_stable_and_unique_per_stage():
    base = RenderFingerprint(
        determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
        seed="0",
        locale="en_US",
        hardware_backend="cpu",
        concurrency_ordering="serial",
        components=(
            FingerprintComponent(role="plan_normalized", digest=_SHA),
            FingerprintComponent(role="ir_room_small", digest=_SHA),
        ),
        toolchain_versions=(ToolchainVersion(component="ffmpeg", version="6.0"),),
        required_capability_manifest=("tts_local_kokoro", "processor_denoise_fft"),
    )
    key_a = base.cache_key("stage_render:cue_001")
    key_b = base.cache_key("stage_render:cue_002")
    assert key_a != key_b
    assert key_a.startswith("sha256:")
    # Stable: same inputs yield same key.
    assert base.cache_key("stage_render:cue_001") == key_a


def test_render_fingerprint_rejects_unbounded_codes_and_unsafe_locale():
    RenderFingerprint(
        determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
        seed="0",
        locale="en_US",
        hardware_backend="cpu",
        concurrency_ordering="serial",
        components=(FingerprintComponent(role="plan_normalized", digest=_SHA),),
        toolchain_versions=(),
        required_capability_manifest=("tts_local_kokoro",),
    )
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            RenderFingerprint(
                determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
                seed="0",
                locale=bad,
                hardware_backend="cpu",
                concurrency_ordering="serial",
                components=(FingerprintComponent(role="plan_normalized", digest=_SHA),),
                toolchain_versions=(),
                required_capability_manifest=(),
            )


def test_render_fingerprint_requires_unique_component_roles_and_manifest():
    with pytest.raises(ValidationError):
        RenderFingerprint(
            determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
            seed="0",
            locale="en_US",
            hardware_backend="cpu",
            concurrency_ordering="serial",
            components=(
                FingerprintComponent(role="dup", digest=_SHA),
                FingerprintComponent(role="dup", digest=_SHA),
            ),
            toolchain_versions=(),
            required_capability_manifest=(),
        )
    with pytest.raises(ValidationError):
        RenderFingerprint(
            determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
            seed="0",
            locale="en_US",
            hardware_backend="cpu",
            concurrency_ordering="serial",
            components=(FingerprintComponent(role="plan_normalized", digest=_SHA),),
            toolchain_versions=(),
            required_capability_manifest=("dup", "dup"),
        )
