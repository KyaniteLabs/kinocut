"""Static code-owned adapter registry and capability preflight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import islice
import logging
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound._errors import SoundContractError
from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult
from kinocut_sound.limits import MAX_S3_REGISTRY_ADAPTERS

logger = logging.getLogger(__name__)


class RegistryError(SoundContractError):
    """Fail-closed static registry error."""


def _error(message: str, code: str) -> RegistryError:
    return RegistryError(message, code=code, suggested_action={"auto_fix": False})


def _registry_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("adapter identifier must be a string")
    checked = BoundedCode(value)
    if ":" in checked or "." in checked or checked != checked.lower():
        raise ValueError("adapter identifiers cannot be import or class paths")
    return checked


@runtime_checkable
class Adapter(Protocol):
    """Minimal typed adapter surface compiled into the static registry."""

    descriptor: AdapterDescriptor

    def probe(self) -> CapabilityResult:
        """Report capability availability without rendering."""


AdapterConstructor = Callable[[], Adapter]


@dataclass(frozen=True)
class AdapterRegistration:
    """Code-owned constructor plus immutable declared descriptor."""

    descriptor: AdapterDescriptor
    constructor: AdapterConstructor


@dataclass(frozen=True)
class ResolvedAdapter:
    """One instantiated and probed adapter with a validated descriptor snapshot."""

    instance: Adapter
    descriptor: AdapterDescriptor
    capability: CapabilityResult


@dataclass(frozen=True)
class _StoredRegistration:
    descriptor: AdapterDescriptor | None
    constructor: AdapterConstructor


class CapabilityManifestReport(FrozenModel):
    """Required/advisory capability preflight without raw provider detail."""

    ready: bool
    required_unavailable: tuple[str, ...]
    advisory_unavailable: tuple[str, ...]
    results: tuple[CapabilityResult, ...]


def _bounded_items(values: object) -> tuple[tuple[object, object], ...]:
    try:
        items = tuple(
            islice(values.items(), MAX_S3_REGISTRY_ADAPTERS + 1)  # type: ignore[attr-defined]
        )
    except Exception:
        logger.warning("registry mapping traversal failed")
        raise _error("adapter registry is invalid", "invalid_registry") from None
    if len(items) > MAX_S3_REGISTRY_ADAPTERS:
        raise _error("adapter registry exceeds its ceiling", "registry_too_large")
    return items


def _descriptor_snapshot(value: object) -> AdapterDescriptor:
    try:
        payload = value.model_dump(mode="python")  # type: ignore[attr-defined]
        return AdapterDescriptor.model_validate(payload)
    except Exception:
        logger.warning("adapter descriptor validation failed")
        raise _error("adapter descriptor is invalid", "adapter_contract_invalid") from None


def _checked_ids(values: object) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("registry identifier traversal failed")
        raise _error("capability identifiers are invalid", "invalid_capability_manifest") from None
    if len(items) > MAX_S3_REGISTRY_ADAPTERS:
        raise _error("capability manifest exceeds its ceiling", "capability_manifest_too_large")
    try:
        checked = tuple(_registry_id(item) for item in items)
    except (TypeError, ValueError):
        raise _error("capability identifiers are invalid", "invalid_capability_manifest") from None
    if len(set(checked)) != len(checked):
        raise _error("capability identifiers must be unique", "duplicate_capability")
    return tuple(sorted(checked))


class AdapterRegistry:
    """Sealed static constructor registry; configuration can only select ids."""

    def __init__(
        self,
        constructors: Mapping[str, AdapterRegistration | AdapterConstructor],
    ) -> None:
        if not isinstance(constructors, Mapping):
            raise _error("adapter registry must be a code mapping", "invalid_registry")
        copied: dict[str, _StoredRegistration] = {}
        for raw_id, value in _bounded_items(constructors):
            try:
                adapter_id = _registry_id(raw_id)
            except (TypeError, ValueError):
                raise _error("adapter registry identifier is invalid", "invalid_registry") from None
            if adapter_id in copied:
                raise _error("adapter registry identifiers must be unique", "invalid_registry")
            copied[adapter_id] = self._normalize_registration(adapter_id, value)
        self._registrations = MappingProxyType(copied)

    @staticmethod
    def _normalize_registration(
        adapter_id: str,
        value: object,
    ) -> _StoredRegistration:
        if isinstance(value, AdapterRegistration):
            descriptor = _descriptor_snapshot(value.descriptor)
            if descriptor.adapter_id != adapter_id or not callable(value.constructor):
                raise _error("adapter registration is inconsistent", "invalid_registry")
            return _StoredRegistration(descriptor=descriptor, constructor=value.constructor)
        if not callable(value):
            raise _error("adapter constructor must be callable", "invalid_registry")
        return _StoredRegistration(descriptor=None, constructor=value)

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        """Return sealed sorted identifiers."""

        return tuple(sorted(self._registrations))

    def contains(self, adapter_id: str) -> bool:
        """Return whether an identifier is compiled into the sealed registry."""

        try:
            checked = _registry_id(adapter_id)
        except (TypeError, ValueError):
            return False
        return checked in self._registrations

    def declared_descriptor(self, adapter_id: str) -> AdapterDescriptor:
        """Return static metadata without constructing or probing the adapter."""

        checked = self._checked_id(adapter_id)
        registration = self._registrations.get(checked)
        if registration is None:
            raise _error("adapter is not compiled into the registry", "adapter_unlisted")
        if registration.descriptor is None:
            raise _error("static adapter descriptor is required", "static_descriptor_required")
        return registration.descriptor

    def _checked_id(self, adapter_id: str) -> str:
        try:
            return _registry_id(adapter_id)
        except (TypeError, ValueError):
            raise _error("adapter identifier is invalid", "invalid_adapter_id") from None

    def _registration(self, adapter_id: str) -> tuple[str, _StoredRegistration]:
        checked = self._checked_id(adapter_id)
        registration = self._registrations.get(checked)
        if registration is None:
            raise _error("adapter is not compiled into the registry", "adapter_unlisted")
        return checked, registration

    def _instantiate(
        self,
        adapter_id: str,
        registration: _StoredRegistration,
    ) -> tuple[Adapter, AdapterDescriptor]:
        try:
            instance = registration.constructor()
            if not isinstance(instance, Adapter):
                raise TypeError("adapter protocol mismatch")
            descriptor = _descriptor_snapshot(instance.descriptor)
        except RegistryError:
            raise
        except Exception:
            logger.warning("adapter construction or descriptor access failed")
            raise _error("adapter contract is invalid", "adapter_contract_invalid") from None
        expected = registration.descriptor
        if descriptor.adapter_id != adapter_id or (expected is not None and descriptor != expected):
            raise _error("adapter descriptor mismatch", "adapter_contract_invalid")
        return instance, descriptor

    @staticmethod
    def _probe_instance(instance: Adapter, descriptor: AdapterDescriptor) -> CapabilityResult:
        try:
            raw_result = instance.probe()
            payload = raw_result.model_dump(mode="python")
            result = CapabilityResult.model_validate(payload)
        except Exception:
            logger.warning("adapter capability probe failed validation")
            raise _error("adapter probe contract is invalid", "probe_contract_invalid") from None
        if result.adapter_id != descriptor.adapter_id:
            raise _error("adapter probe identifier mismatch", "probe_contract_invalid")
        return result

    def _resolve_and_probe(self, adapter_id: str) -> ResolvedAdapter:
        checked, registration = self._registration(adapter_id)
        instance, descriptor = self._instantiate(checked, registration)
        capability = self._probe_instance(instance, descriptor)
        return ResolvedAdapter(instance=instance, descriptor=descriptor, capability=capability)

    def resolve(
        self,
        adapter_id: str,
        *,
        kind: str,
        locality: AdapterLocality | None = None,
    ) -> ResolvedAdapter:
        """Instantiate once, snapshot, probe, and verify descriptor selectors."""

        resolved = self._resolve_and_probe(adapter_id)
        if resolved.descriptor.kind != kind:
            raise _error("adapter kind mismatch", "adapter_contract_invalid")
        if locality is not None and resolved.descriptor.locality is not locality:
            raise _error("adapter locality mismatch", "adapter_contract_invalid")
        return resolved

    def probe(self, adapter_id: str) -> CapabilityResult:
        """Probe one adapter; ordinary failures become explicit unavailable."""

        try:
            return self._resolve_and_probe(adapter_id).capability
        except RegistryError as error:
            if error.code == "invalid_adapter_id":
                raise
            reason = {
                "adapter_unlisted": "adapter_unlisted",
                "adapter_contract_invalid": "adapter_contract_invalid",
                "probe_contract_invalid": "probe_contract_invalid",
            }.get(error.code, "constructor_failed")
            return CapabilityResult(
                adapter_id=self._checked_id(adapter_id),
                available=False,
                reason_code=reason,
                remediation="Select or repair an installed allowlisted adapter.",
            )

    def require(
        self,
        adapter_id: str,
        *,
        kind: str,
        locality: AdapterLocality | None = None,
    ) -> ResolvedAdapter:
        """Return the same validated instance that was capability-probed."""

        try:
            resolved = self.resolve(adapter_id, kind=kind, locality=locality)
        except RegistryError as error:
            if error.code == "adapter_unlisted":
                raise _error("required adapter is unavailable", "adapter_unavailable") from None
            raise
        if not resolved.capability.available:
            raise _error("required adapter is unavailable", "adapter_unavailable")
        return resolved

    def probe_manifest(
        self,
        *,
        required_ids: object,
        advisory_ids: object,
        demanded_render: bool,
    ) -> CapabilityManifestReport:
        """Probe required and advisory capabilities before rendering."""

        required = _checked_ids(required_ids)
        advisory = _checked_ids(advisory_ids)
        if set(required) & set(advisory):
            raise _error("capability classes must not overlap", "duplicate_capability")
        results = tuple(self.probe(adapter_id) for adapter_id in (*required, *advisory))
        by_id = {result.adapter_id: result for result in results}
        required_missing = tuple(item for item in required if not by_id[item].available)
        advisory_missing = tuple(item for item in advisory if not by_id[item].available)
        if demanded_render and required_missing:
            raise _error("required capability is unavailable", "required_capability_unavailable")
        return CapabilityManifestReport(
            ready=not required_missing,
            required_unavailable=required_missing,
            advisory_unavailable=advisory_missing,
            results=results,
        )
