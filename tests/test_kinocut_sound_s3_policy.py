"""Static sound adapter registry acceptance tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult, CostDisclosure
from kinocut_sound.registry import AdapterRegistry, RegistryError


class _Adapter:
    def __init__(self, descriptor: AdapterDescriptor, available: bool = True) -> None:
        self.descriptor = descriptor
        self._available = available

    def probe(self) -> CapabilityResult:
        if self._available:
            return CapabilityResult(adapter_id=self.descriptor.adapter_id, available=True)
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="dependency_missing",
            remediation="Install the optional adapter dependency.",
        )


def _local(adapter_id: str = "tts_local") -> _Adapter:
    return _Adapter(
        AdapterDescriptor(
            adapter_id=adapter_id,
            kind="tts",
            locality=AdapterLocality.LOCAL,
            provider_class="local",
        )
    )


def _cloud(adapter_id: str = "tts_cloud") -> _Adapter:
    return _Adapter(
        AdapterDescriptor(
            adapter_id=adapter_id,
            kind="tts",
            locality=AdapterLocality.CLOUD,
            provider_class="cloud",
            cost_disclosure=CostDisclosure(
                provider_id="provider_a",
                region="us-east-1",
                data_classes=("reference_audio",),
                retention_ceiling_days=7,
                estimated_cost_usd_per_call=0.1,
                confirmed=True,
            ),
        )
    )


def test_static_registry_probes_explicit_unavailable_and_never_imports_config() -> None:
    registry = AdapterRegistry({"tts_local": _local})
    assert registry.probe("tts_local").available is True
    missing = registry.probe("tts_missing")
    assert (missing.available, missing.reason_code) == (False, "adapter_unlisted")
    with pytest.raises(RegistryError) as exc_info:
        registry.require("tts_missing", kind="tts")
    assert exc_info.value.code == "adapter_unavailable"
    with pytest.raises((ValidationError, RegistryError, ValueError)):
        registry.probe("pkg.module:Adapter")


def test_registry_rejects_descriptor_mismatch_and_redacts_probe_failure() -> None:
    registry = AdapterRegistry({"tts_local": lambda: _local("different_id")})
    with pytest.raises(RegistryError) as exc_info:
        registry.require("tts_local", kind="tts")
    assert exc_info.value.code == "adapter_contract_invalid"

    def broken() -> _Adapter:
        raise RuntimeError("PRIVATE_CONSTRUCTOR_MARKER")

    unavailable = AdapterRegistry({"tts_broken": broken}).probe("tts_broken")
    assert unavailable.available is False
    assert "PRIVATE_CONSTRUCTOR_MARKER" not in repr(unavailable)


def test_required_capability_absence_blocks_render_but_advisory_is_reported() -> None:
    registry = AdapterRegistry(
        {
            "tts_local": _local,
            "analyzer_optional": lambda: _Adapter(
                AdapterDescriptor(
                    adapter_id="analyzer_optional",
                    kind="analyzer",
                    locality=AdapterLocality.LOCAL,
                    provider_class="local",
                ),
                available=False,
            ),
        }
    )
    report = registry.probe_manifest(
        required_ids=("tts_local",),
        advisory_ids=("analyzer_optional",),
        demanded_render=True,
    )
    assert report.ready is True
    assert report.advisory_unavailable == ("analyzer_optional",)
    with pytest.raises(RegistryError) as exc_info:
        registry.probe_manifest(required_ids=("tts_missing",), advisory_ids=(), demanded_render=True)
    assert exc_info.value.code == "required_capability_unavailable"
