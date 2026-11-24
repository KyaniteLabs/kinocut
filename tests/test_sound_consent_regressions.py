"""Consent retention and delivery-policy regressions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.consent import RetentionPolicy
from kinocut_sound.delivery import DeliveryPolicy, DeliveryPreset, LoudnessTarget


def test_misspelled_retention_code_is_rejected_instead_of_meaning_keep() -> None:
    with pytest.raises(ValidationError):
        RetentionPolicy(biometric_retention="delete_on_revoke", audit_retention="keep_5y")


def test_delivery_preset_drives_loudness_and_true_peak_ceiling() -> None:
    policy = DeliveryPolicy(preset=DeliveryPreset.BROADCAST_EBU_R128_MINUS_23)
    assert policy.loudness.integrated_lufs == -23.0
    assert policy.loudness.true_peak_dbtp == -2.0
    assert policy.true_peak_ceiling_dbtp == -2.0


def test_explicit_delivery_values_still_win_over_the_preset() -> None:
    policy = DeliveryPolicy(
        preset=DeliveryPreset.BROADCAST_EBU_R128_MINUS_23,
        loudness=LoudnessTarget(integrated_lufs=-18, true_peak_dbtp=-2),
        true_peak_ceiling_dbtp=-3,
    )
    assert policy.loudness.integrated_lufs == -18.0
    assert policy.true_peak_ceiling_dbtp == -3


def test_default_delivery_policy_is_unchanged() -> None:
    policy = DeliveryPolicy()
    assert policy.preset is DeliveryPreset.STREAM_MINUS_14
    assert policy.loudness.integrated_lufs == -14.0
    assert policy.true_peak_ceiling_dbtp == -1.0
