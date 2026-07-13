"""Static code-owned adapter registry and capability preflight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import islice
import logging
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound._errors import SoundContractError
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.limits import MAX_S3_REGISTRY_ADAPTERS

logger = logging.getLogger(__name__)


class RegistryError(SoundContractError):
    """Fail-closed static registry error."""


def _error(message: str, code: str) -> RegistryError:
    return RegistryError(message, code=code, suggested_action={"auto_fix": False})


def _registry_id(value: str) -> str:
    checked = BoundedCode(value)
    if ":" in checked:
        raise ValueError("adapter identifiers cannot be import or class paths")
    return checked


@runtime_checkable
class Adapter(Protocol):
    """Minimal typed adapter surface compiled into the static registry."""

    descriptor: AdapterDescriptor

    def probe(self) -> CapabilityResult:
        """Report capability availability without performing a render."""


AdapterConstructor = Callable[[], Adapter]


class CapabilityManifestReport(FrozenModel):
    """Required/advisory capability preflight without raw provider detail."""

    ready: bool
    required_unavailable: tuple[str, ...]
    advisory_unavailable: tuple[str, ...]
    results: tuple[CapabilityResult, ...]


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
    """Immutable constructor allowlist copied from code, never from config."""

    def __init__(self, constructors: Mapping[str, AdapterConstructor]) -> None:
        if not isinstance(constructors, Mapping):
            raise _error("adapter registry must be a code mapping", "invalid_registry")
        if len(constructors) > MAX_S3_REGISTRY_ADAPTERS:
            raise _error("adapter registry exceeds its ceiling", "registry_too_large")
        copied: dict[str, AdapterConstructor] = {}
        for adapter_id, constructor in constructors.items():
            try:
                checked_id = _registry_id(adapter_id)
            except (TypeError, ValueError):
                raise _error("adapter registry identifier is invalid", "invalid_registry") from None
            if not callable(constructor):
                raise _error("adapter constructor must be callable", "invalid_registry")
            copied[checked_id] = constructor
        self._constructors = MappingProxyType(copied)

    @property
    def adapter_ids(self) -> tuple[str, ...]:
        """Return the sealed, sorted code-owned identifiers."""

        return tuple(sorted(self._constructors))

    def _instantiate(self, adapter_id: str) -> Adapter:
        try:
            adapter_id = _registry_id(adapter_id)
        except (TypeError, ValueError):
            raise _error("adapter identifier is invalid", "invalid_adapter_id") from None
        constructor = self._constructors.get(adapter_id)
        if constructor is None:
            raise _error("adapter is not compiled into the registry", "adapter_unlisted")
        try:
            adapter = constructor()
        except Exception:
            logger.warning("adapter constructor failed")
            raise _error("adapter constructor failed", "adapter_constructor_failed") from None
        try:
            if not isinstance(adapter, Adapter):
                raise TypeError("adapter protocol mismatch")
            descriptor = AdapterDescriptor.model_validate(adapter.descriptor.model_dump(mode="python"))
        except Exception:
            logger.warning("adapter contract validation failed")
            raise _error("adapter does not satisfy the typed contract", "adapter_contract_invalid") from None
        if descriptor.adapter_id != adapter_id:
            raise _error("adapter descriptor identifier mismatch", "adapter_contract_invalid")
        return adapter

    def resolve(
        self,
        adapter_id: str,
        *,
        kind: str,
        locality: AdapterLocality | None = None,
    ) -> Adapter:
        """Resolve one compiled adapter and verify its descriptor exactly."""

        adapter = self._instantiate(adapter_id)
        if adapter.descriptor.kind != kind:
            raise _error("adapter kind mismatch", "adapter_contract_invalid")
        if locality is not None and adapter.descriptor.locality is not locality:
            raise _error("adapter locality mismatch", "adapter_contract_invalid")
        return adapter

    def probe(self, adapter_id: str) -> CapabilityResult:
        """Probe one compiled adapter; every failure becomes explicit unavailable."""

        try:
            adapter = self._instantiate(adapter_id)
        except RegistryError as exc:
            if exc.code == "invalid_adapter_id":
                raise
            reason = "adapter_unlisted" if exc.code == "adapter_unlisted" else "constructor_failed"
            return CapabilityResult(
                adapter_id=BoundedCode(adapter_id),
                available=False,
                reason_code=reason,
                remediation="Select an installed allowlisted adapter.",
            )
        try:
            result = adapter.probe()
        except Exception:
            logger.warning("adapter capability probe failed")
            return CapabilityResult(
                adapter_id=adapter.descriptor.adapter_id,
                available=False,
                reason_code="probe_failed",
                remediation="Check the optional adapter dependency.",
            )
        if result.adapter_id != adapter.descriptor.adapter_id:
            return CapabilityResult(
                adapter_id=adapter.descriptor.adapter_id,
                available=False,
                reason_code="probe_contract_invalid",
                remediation="Repair the adapter capability probe.",
            )
        return result

    def require(
        self,
        adapter_id: str,
        *,
        kind: str,
        locality: AdapterLocality | None = None,
    ) -> Adapter:
        """Resolve and require an available adapter for demanded work."""

        try:
            adapter = self.resolve(adapter_id, kind=kind, locality=locality)
        except RegistryError as exc:
            if exc.code == "adapter_unlisted":
                raise _error("required adapter is unavailable", "adapter_unavailable") from None
            raise
        result = self.probe(adapter_id)
        if not result.available:
            raise _error("required adapter is unavailable", "adapter_unavailable")
        return adapter

    def probe_manifest(
        self,
        *,
        required_ids: object,
        advisory_ids: object,
        demanded_render: bool,
    ) -> CapabilityManifestReport:
        """Probe required and advisory capabilities before any render starts."""

        required = _checked_ids(required_ids)
        advisory = _checked_ids(advisory_ids)
        if set(required) & set(advisory):
            raise _error("capability classes must not overlap", "duplicate_capability")
        results = tuple(self.probe(adapter_id) for adapter_id in (*required, *advisory))
        by_id = {result.adapter_id: result for result in results}
        required_missing = tuple(item for item in required if not by_id[item].available)
        advisory_missing = tuple(item for item in advisory if not by_id[item].available)
        if demanded_render and required_missing:
            raise _error(
                "required capability is unavailable",
                "required_capability_unavailable",
            )
        return CapabilityManifestReport(
            ready=not required_missing,
            required_unavailable=required_missing,
            advisory_unavailable=advisory_missing,
            results=results,
        )
