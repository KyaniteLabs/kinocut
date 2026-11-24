"""Independent-review regressions for the sound adapter registry."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult
from kinocut_sound.limits import MAX_S3_REGISTRY_ADAPTERS
from kinocut_sound.registry import AdapterRegistration, AdapterRegistry, RegistryError
from tests.test_kinocut_sound_s3_policy import _Adapter, _local


def _registration(factory: object, descriptor: AdapterDescriptor) -> AdapterRegistration:
    return AdapterRegistration(descriptor=descriptor, constructor=factory)


def _local_registration(factory: object = _local) -> AdapterRegistration:
    return _registration(factory, _local().descriptor)


class _LyingMapping(Mapping[str, AdapterRegistration]):
    def __init__(self, count: int) -> None:
        self._count = count

    def __len__(self) -> int:
        return 0

    def __iter__(self) -> Iterator[str]:
        return (f"tts_{index}" for index in range(self._count))

    def __getitem__(self, key: str) -> AdapterRegistration:
        return self._registration(key)

    @staticmethod
    def _registration(key: str) -> AdapterRegistration:
        descriptor = _local(key).descriptor
        return AdapterRegistration(
            descriptor=descriptor,
            constructor=lambda descriptor=descriptor: _Adapter(descriptor),
        )

    def items(self) -> Iterator[tuple[str, AdapterRegistration]]:
        return ((key, self._registration(key)) for key in self)


def test_registry_bounds_mapping_items_despite_lying_len() -> None:
    AdapterRegistry(_LyingMapping(MAX_S3_REGISTRY_ADAPTERS))
    with pytest.raises(RegistryError) as exc_info:
        AdapterRegistry(_LyingMapping(MAX_S3_REGISTRY_ADAPTERS + 1))
    assert exc_info.value.code == "registry_too_large"


def test_registry_constructs_once_probes_same_instance_and_keeps_snapshot() -> None:
    calls: list[int] = []

    class AlternatingAdapter(_Adapter):
        def __init__(self, serial: int) -> None:
            super().__init__(_local().descriptor)
            self.serial = serial

    def alternating() -> AlternatingAdapter:
        calls.append(len(calls) + 1)
        return AlternatingAdapter(calls[-1])

    resolved = AdapterRegistry({"tts_local": _local_registration(alternating)}).require(
        "tts_local", kind="tts", locality=AdapterLocality.LOCAL
    )
    assert calls == [1]
    assert resolved.instance.serial == 1
    assert resolved.capability.available is True
    assert resolved.descriptor == _local().descriptor


def test_registry_sanitizes_wrong_descriptor_and_capability_properties() -> None:
    marker = "PRIVATE_REGISTRY_PROPERTY_MARKER"

    class WrongDescriptor:
        @property
        def descriptor(self) -> AdapterDescriptor:
            raise RuntimeError(marker)

        def probe(self) -> CapabilityResult:
            return CapabilityResult(adapter_id="tts_local", available=True)

    registry = AdapterRegistry({"tts_local": _local_registration(WrongDescriptor)})
    result = registry.probe("tts_local")
    assert result.reason_code == "adapter_contract_invalid"
    assert marker not in repr(result)

    class WrongCapability(_Adapter):
        def probe(self) -> object:
            return {"adapter_id": "tts_local", "available": "yes", "marker": marker}

    registry = AdapterRegistry({"tts_local": _local_registration(lambda: WrongCapability(_local().descriptor))})
    result = registry.probe("tts_local")
    assert result.reason_code == "probe_contract_invalid"
    assert marker not in repr(result)
