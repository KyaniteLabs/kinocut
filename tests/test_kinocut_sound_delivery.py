"""RED-first tests for the ``kinocut_sound`` delivery policy contract.

Delivery binds the named loudness preset, true-peak ceiling, stem layout,
deterministic stem-recombination policy, and distribution metadata fields.
The named presets are standards-specific (ruling #9): ``stream_-14`` default,
``podcast_-16``, ``broadcast_ebu_r128_-23``, ``broadcast_atsc_a85_-24``. A
preset is never an alias for another (ruling #9).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.delivery import (
    DEFAULT_PRESET,
    DeliveryPolicy,
    DeliveryPreset,
    LoudnessTarget,
    StemLayout,
    StemRecombinationPolicy,
)


def test_delivery_presets_are_closed_and_match_named_targets():
    assert {p.value for p in DeliveryPreset} == {
        "stream_-14",
        "podcast_-16",
        "broadcast_ebu_r128_-23",
        "broadcast_atsc_a85_-24",
    }
    assert DEFAULT_PRESET is DeliveryPreset.STREAM_MINUS_14
    for preset, target in (
        (DeliveryPreset.STREAM_MINUS_14, -14.0),
        (DeliveryPreset.PODCAST_MINUS_16, -16.0),
        (DeliveryPreset.BROADCAST_EBU_R128_MINUS_23, -23.0),
        (DeliveryPreset.BROADCAST_ATSC_A85_MINUS_24, -24.0),
    ):
        assert LoudnessTarget.for_preset(preset).integrated_lufs == target


def test_loudness_target_enforces_tolerance_and_true_peak_ceiling():
    LoudnessTarget(integrated_lufs=-14.0, tolerance_lu=1.0, true_peak_dbtp=-1.0)
    for bad_lufs in (-14.0, -16.0):  # out-of-preset values are explicit-only
        LoudnessTarget(integrated_lufs=bad_lufs, tolerance_lu=1.0, true_peak_dbtp=-1.0)
    with pytest.raises(ValidationError):
        LoudnessTarget(integrated_lufs=-14.0, tolerance_lu=0.0, true_peak_dbtp=-1.0)
    with pytest.raises(ValidationError):
        LoudnessTarget(integrated_lufs=-14.0, tolerance_lu=1.0, true_peak_dbtp=0.0)


def test_stem_layout_requires_unique_bounded_codes():
    StemLayout(stem_ids=("stem_dialog", "stem_ambience", "stem_sfx"))
    with pytest.raises(ValidationError):
        StemLayout(stem_ids=("stem_dialog", "stem_dialog"))
    with pytest.raises(ValidationError):
        StemLayout(stem_ids=("with space",))


def test_stem_recombination_policy_enforces_tolerance_class():
    StemRecombinationPolicy(tolerance_lsb_at_24bit=1, comparison_reference="pre_master")
    with pytest.raises(ValidationError):
        StemRecombinationPolicy(tolerance_lsb_at_24bit=2, comparison_reference="pre_master")
    with pytest.raises(ValidationError):
        StemRecombinationPolicy(tolerance_lsb_at_24bit=1, comparison_reference="invalid")


def test_delivery_policy_defaults_to_stream_minus_14_with_pre_master_reference():
    policy = DeliveryPolicy()
    assert policy.preset is DeliveryPreset.STREAM_MINUS_14
    assert policy.loudness.integrated_lufs == -14.0
    assert policy.true_peak_ceiling_dbtp == -1.0
    assert policy.stems.stem_ids == ()
    assert policy.recombination.comparison_reference == "pre_master"


def test_delivery_policy_rejects_unbounded_metadata_codes():
    ok = DeliveryPolicy(metadata_codes=("isrc", "title_hash"))
    assert ok.metadata_codes == ("isrc", "title_hash")
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            DeliveryPolicy(metadata_codes=(bad,))


def test_delivery_policy_requires_pre_master_reference_when_master_only_limiting_enabled():
    # If master-only limiting is enabled, the plan must also request a pre-master
    # reference (ruling #7 / mix policy).
    policy = DeliveryPolicy(
        master_only_limiting_enabled=True,
        recombination=StemRecombinationPolicy(
            tolerance_lsb_at_24bit=1,
            comparison_reference="pre_master",
        ),
    )
    assert policy.master_only_limiting_enabled is True
    with pytest.raises(ValidationError):
        DeliveryPolicy(
            master_only_limiting_enabled=True,
            recombination=StemRecombinationPolicy(
                tolerance_lsb_at_24bit=1,
                comparison_reference="post_master",
            ),
        )
