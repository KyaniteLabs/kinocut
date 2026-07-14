"""RED-first tests for the ``kinocut_sound`` capability contract.

The capability contract exposes typed adapter descriptors and a fail-closed
``CapabilityResult``. Adapter locality (local vs cloud) is closed; a cloud
adapter must disclose cost/retention/region before any call. Required
capabilities that probe unavailable yield a validation error for a demanded
render — never a silent fallback to remote. The static code-owned registry
itself is the S3 leaf; here we own the typed contract shape.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
    CostDisclosure,
)
from kinocut_sound.validation import ADAPTER_KINDS


def test_adapter_locality_is_closed():
    assert {loc.value for loc in AdapterLocality} == {"local", "cloud"}


def test_adapter_kinds_are_closed():
    assert frozenset({"tts", "processor", "spatializer", "asset", "analyzer"}) == ADAPTER_KINDS


def test_adapter_descriptor_requires_bounded_codes_and_locality():
    AdapterDescriptor(
        adapter_id="tts_local_kokoro",
        kind="tts",
        locality=AdapterLocality.LOCAL,
        provider_class="local",
    )
    for bad_id in ("with space", "../x", "1lead"):
        with pytest.raises(ValidationError):
            AdapterDescriptor(
                adapter_id=bad_id,
                kind="tts",
                locality=AdapterLocality.LOCAL,
                provider_class="local",
            )
    for bad_kind in ("unknown", "tts-local"):
        with pytest.raises(ValidationError):
            AdapterDescriptor(
                adapter_id="x",
                kind=bad_kind,
                locality=AdapterLocality.LOCAL,
                provider_class="local",
            )


def test_cloud_descriptor_requires_cost_disclosure_with_provider_and_territory():
    with pytest.raises(ValidationError):
        AdapterDescriptor(
            adapter_id="tts_cloud_elevenlabs",
            kind="tts",
            locality=AdapterLocality.CLOUD,
            provider_class="elevenlabs",
            cost_disclosure=None,
        )
    desc = AdapterDescriptor(
        adapter_id="tts_cloud_elevenlabs",
        kind="tts",
        locality=AdapterLocality.CLOUD,
        provider_class="elevenlabs",
        cost_disclosure=CostDisclosure(
            provider_id="elevenlabs",
            region="us-east-1",
            data_classes=("reference_audio",),
            retention_ceiling_days=30,
            estimated_cost_usd_per_call=0.05,
            confirmed=False,
        ),
    )
    assert desc.cost_disclosure is not None
    assert desc.cost_disclosure.confirmed is False


def test_cost_disclosure_rejects_unbounded_codes_and_negative_cost():
    CostDisclosure(
        provider_id="elevenlabs",
        region="us-east-1",
        data_classes=("reference_audio",),
        retention_ceiling_days=30,
        estimated_cost_usd_per_call=0.05,
        confirmed=False,
    )
    for bad in ("with space", "../x"):
        with pytest.raises(ValidationError):
            CostDisclosure(
                provider_id=bad,
                region="us-east-1",
                data_classes=("reference_audio",),
                retention_ceiling_days=30,
                estimated_cost_usd_per_call=0.05,
                confirmed=False,
            )
    with pytest.raises(ValidationError):
        CostDisclosure(
            provider_id="x",
            region="us-east-1",
            data_classes=("reference_audio",),
            retention_ceiling_days=30,
            estimated_cost_usd_per_call=-0.01,
            confirmed=False,
        )


def test_capability_result_is_fail_closed_with_reason_when_unavailable():
    ok = CapabilityResult(
        adapter_id="tts_local_kokoro",
        available=True,
        reason_code=None,
        remediation=None,
    )
    assert ok.available is True
    unavailable = CapabilityResult(
        adapter_id="tts_cloud_elevenlabs",
        available=False,
        reason_code="missing_capability",
        remediation="Install or authorize the adapter.",
    )
    assert unavailable.reason_code == "missing_capability"
    with pytest.raises(ValidationError):
        CapabilityResult(adapter_id="x", available=False, reason_code=None, remediation=None)
    with pytest.raises(ValidationError):
        CapabilityResult(
            adapter_id="x",
            available=True,
            reason_code="x",
            remediation="y",
        )


def test_capability_result_rejects_unbounded_codes_and_unsafe_advisory():
    with pytest.raises(ValidationError):
        CapabilityResult(
            adapter_id="with space",
            available=False,
            reason_code="x",
            remediation="install it",
        )
    with pytest.raises(ValidationError):
        CapabilityResult(
            adapter_id="x",
            available=False,
            reason_code="x",
            remediation="/etc/passwd is unsafe",
        )
