"""Adversarial sound adapter registry and descriptor regressions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult
from kinocut_sound.registry import AdapterRegistry, RegistryError
from tests.test_kinocut_sound_s3_policy import _cloud, _local


def test_registry_is_a_sealed_copy_and_checks_kind_and_locality() -> None:
    constructors = {"tts_local": _local}
    registry = AdapterRegistry(constructors)
    constructors.clear()
    resolved = registry.require("tts_local", kind="tts", locality=AdapterLocality.LOCAL)
    assert resolved.descriptor.adapter_id == "tts_local"
    with pytest.raises(RegistryError):
        registry.require("tts_local", kind="analyzer")
    with pytest.raises(RegistryError):
        registry.require("tts_local", kind="tts", locality=AdapterLocality.CLOUD)


def test_local_descriptor_cannot_smuggle_cloud_disclosure() -> None:
    with pytest.raises(ValidationError):
        AdapterDescriptor(
            adapter_id="tts_local",
            kind="tts",
            locality=AdapterLocality.LOCAL,
            provider_class="local",
            cost_disclosure=_cloud().descriptor.cost_disclosure,
        )


def test_probe_exception_is_normalized_without_marker_or_cause() -> None:
    marker = "PRIVATE_PROBE_MARKER"

    class BrokenProbe:
        descriptor = _local().descriptor

        def probe(self) -> CapabilityResult:
            raise RuntimeError(marker)

    result = AdapterRegistry({"tts_local": BrokenProbe}).probe("tts_local")
    assert result.reason_code == "probe_contract_invalid"
    assert marker not in repr(result)
