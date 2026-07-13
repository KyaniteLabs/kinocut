"""Fake D41 port and cloud asset adapter tests for the S8 world leaf.

Covers required rows:
* fake D41 port probes available and returns a neutral audition result.
* cloud asset adapter probes unavailable without network.

Plus hardening: the local fake adapters conform to the typed port protocols;
the cloud adapter never silently selects itself; descriptors validate against
the S3 registry contract shape.
"""

from __future__ import annotations

import pytest

from kinocut_sound.capability import AdapterDescriptor, AdapterLocality
from kinocut_sound.registry import Adapter
from kinocut_sound.world import (
    AuditionPort,
    BedKind,
    BedPort,
    BedSpec,
    CLOUD_ASSET_ADAPTER_ID,
    CloudAssetAdapter,
    D41_AUDITION_FAKE_ADAPTER_ID,
    D41_BED_FAKE_ADAPTER_ID,
    FakeD41Port,
    LOCAL_ASSET_ADAPTER_ID,
    LocalFakeAssetAdapter,
    LocalFakeAuditionAdapter,
    LocalFakeBedAdapter,
    default_fake_d41_port,
)

_SHA = "sha256:" + "a" * 64


def test_fake_d41_port_probes_available_and_returns_neutral_audition_result():
    port = default_fake_d41_port()
    bed_probe, audition_probe = port.probe()
    assert bed_probe.available is True
    assert audition_probe.available is True
    # The audition port returns a neutral reel result with human review.
    reel = port.audition.build_audition_reel(
        bed_id="bed_common_room",
        reel_label="reel_001",
        description_hash=_SHA,
    )
    assert reel.bed_id == "bed_common_room"
    assert reel.reel_hash.startswith("sha256:")
    assert reel.human_review_required is True
    # The bed port returns a neutral descriptor with no host path.
    descriptor = port.bed.prepare_bed(
        BedSpec(
            bed_id="bed_common_room",
            kind=BedKind.AMBIENT_BED,
            description_hash=_SHA,
            duration_seconds=120.0,
        )
    )
    assert descriptor.bed_id == "bed_common_room"
    assert descriptor.descriptor_hash.startswith("sha256:")
    serialized = str(descriptor.descriptor_hash) + str(descriptor.bed_id)
    for forbidden in ("/home/", "/etc/", "password"):
        assert forbidden not in serialized


def test_fake_d41_port_adapters_conform_to_typed_protocols():
    port = default_fake_d41_port()
    assert isinstance(port.bed, BedPort)
    assert isinstance(port.audition, AuditionPort)
    assert isinstance(port, FakeD41Port)


def test_local_fake_adapters_satisfy_registry_adapter_protocol():
    bed = LocalFakeBedAdapter()
    audition = LocalFakeAuditionAdapter()
    asset = LocalFakeAssetAdapter()
    assert isinstance(bed, Adapter)
    assert isinstance(audition, Adapter)
    assert isinstance(asset, Adapter)
    # Descriptors validate against the canonical shape.
    for adapter in (bed, audition, asset):
        (AdapterDescriptor.model_validate(adapter.descriptor.model_dump(mode="python")))
    assert bed.descriptor.adapter_id == D41_BED_FAKE_ADAPTER_ID
    assert audition.descriptor.adapter_id == D41_AUDITION_FAKE_ADAPTER_ID
    assert asset.descriptor.adapter_id == LOCAL_ASSET_ADAPTER_ID
    assert asset.descriptor.locality is AdapterLocality.LOCAL


def test_cloud_asset_adapter_probes_unavailable_without_network():
    adapter = CloudAssetAdapter()
    assert isinstance(adapter, Adapter)
    result = adapter.probe()
    assert result.available is False
    assert result.reason_code == "cloud_asset_not_configured"
    assert adapter.descriptor.adapter_id == CLOUD_ASSET_ADAPTER_ID
    assert adapter.descriptor.locality is AdapterLocality.CLOUD
    # The cloud adapter carries a cost disclosure (required for cloud locality).
    assert adapter.descriptor.cost_disclosure is not None
    assert adapter.descriptor.cost_disclosure.confirmed is False


def test_cloud_asset_descriptor_does_not_silently_enable_itself():
    adapter = CloudAssetAdapter()
    # Probing must never raise and must never return available=True.
    for _ in range(3):
        result = adapter.probe()
        assert result.available is False
        # And the remediation is bounded advisory text (no path or URL).
        assert result.remediation is not None
        assert "://" not in result.remediation
        assert "/" not in result.remediation


def test_local_fake_bed_descriptor_is_deterministic():
    port = default_fake_d41_port()
    spec = BedSpec(
        bed_id="bed_common_room",
        kind=BedKind.AMBIENT_BED,
        description_hash=_SHA,
        duration_seconds=120.0,
    )
    a = port.bed.prepare_bed(spec)
    b = port.bed.prepare_bed(spec)
    assert a.descriptor_hash == b.descriptor_hash
    # A different bed id yields a different hash.
    other = port.bed.prepare_bed(spec.model_copy(update={"bed_id": "bed_garden"}))
    assert other.descriptor_hash != a.descriptor_hash


def test_bed_spec_rejects_unbounded_id_and_non_positive_duration():
    with pytest.raises(Exception):
        BedSpec(
            bed_id="not bounded",
            kind=BedKind.ROOM_TONE,
            description_hash=_SHA,
            duration_seconds=10.0,
        )
    with pytest.raises(Exception):
        BedSpec(
            bed_id="bed_x",
            kind=BedKind.ROOM_TONE,
            description_hash=_SHA,
            duration_seconds=0.0,
        )
