"""Adversarial S3 registry, policy, fingerprint, and cache regressions."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    DerivativeDisposition,
    DerivativeOutcome,
)
from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult
from kinocut_sound.limits import MAX_FINGERPRINT_ITEMS, MAX_S3_CACHE_ENTRIES, MAX_S3_PRESETS
from kinocut_sound.provider_policy import select_adapter
from kinocut_sound.registry import AdapterRegistration, AdapterRegistry, RegistryError
from kinocut_sound.s3_cache import AuthorizationAwareCache, AuthorizedLineage, CacheError
from kinocut_sound.s3_fingerprint import CapabilitySnapshot, FingerprintInputs, build_render_fingerprint
from kinocut_sound.sound_config import Preset, PresetCatalog, PresetKind, SoundConfigError

from tests.test_kinocut_sound_s3_policy import (
    _CONTEXT,
    _NOW,
    _SHA_A,
    _SHA_B,
    _Adapter,
    _cloud,
    _cloud_policy,
    _cloud_registration,
    _fingerprint_inputs,
    _ledger,
    _local,
    _payload,
    _request,
    _route,
)


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


@pytest.mark.parametrize(
    "policy_update",
    [
        {"allow_cloud": False},
        {"cloud_execution_confirmed": False},
        {"routes": (_route(provider_id="other"),)},
        {"routes": (_route(region="eu-west-1"),)},
        {"routes": (_route(egress_host="other.provider.test"),)},
        {"routes": (_route(credential_handle="other_key"),)},
    ],
)
def test_cloud_selection_fails_closed_on_each_opt_in_axis(policy_update: dict[str, object]) -> None:
    policy = _cloud_policy().model_copy(update=policy_update)
    with pytest.raises(RegistryError):
        select_adapter(
            AdapterRegistry({"tts_cloud": _cloud_registration()}),
            ("tts_cloud",),
            kind="tts",
            policy=policy,
            ledger=_ledger(),
            request=_request(),
        )


def test_unconfirmed_cloud_disclosure_and_s2_mismatch_are_denied_without_raw_cause() -> None:
    descriptor = _cloud().descriptor
    disclosure = descriptor.cost_disclosure
    assert disclosure is not None
    unconfirmed_descriptor = descriptor.model_copy(
        update={"cost_disclosure": disclosure.model_copy(update={"confirmed": False})}
    )
    registration = AdapterRegistration(
        descriptor=unconfirmed_descriptor,
        constructor=lambda: _Adapter(unconfirmed_descriptor),
    )
    with pytest.raises(RegistryError) as exc_info:
        select_adapter(
            AdapterRegistry({"tts_cloud": registration}),
            ("tts_cloud",),
            kind="tts",
            policy=_cloud_policy(),
            ledger=_ledger(),
            request=_request(),
        )
    assert exc_info.value.__cause__ is None

    gb_request = _request().model_copy(
        update={
            "territory": "GB",
            "context": AuthorizationContext(
                operation="voice_clone",
                project_id="project_a",
                provider_class="cloud",
                territory="GB",
            ),
        }
    )
    with pytest.raises(RegistryError) as exc_info:
        select_adapter(
            AdapterRegistry({"tts_cloud": _cloud_registration()}),
            ("tts_cloud",),
            kind="tts",
            policy=_cloud_policy(),
            ledger=_ledger(),
            request=gb_request,
        )
    assert exc_info.value.code == "cloud_authorization_denied"
    assert exc_info.value.__cause__ is None


def test_fingerprint_vectors_are_canonically_sorted_and_duplicates_rejected() -> None:
    inputs = _fingerprint_inputs()
    reversed_inputs = inputs.model_copy(
        update={
            "byte_digests": tuple(reversed(inputs.byte_digests)),
            "toolchain_versions": tuple(reversed(inputs.toolchain_versions)),
        }
    )
    assert build_render_fingerprint(inputs).digest() == build_render_fingerprint(reversed_inputs).digest()
    with pytest.raises(ValidationError):
        FingerprintInputs(
            **{
                **inputs.model_dump(),
                "toolchain_versions": (("ffmpeg", "7.1"), ("ffmpeg", "8.0")),
            }
        )
    duplicate = inputs.capability_manifest[0]
    with pytest.raises(ValidationError):
        FingerprintInputs(
            **{
                **inputs.model_dump(),
                "capability_manifest": (
                    duplicate,
                    CapabilitySnapshot(**duplicate.model_dump()),
                ),
            }
        )


def test_fingerprint_completeness_is_construction_time_enforced() -> None:
    payload = _fingerprint_inputs().model_dump()
    for required in (
        "normalized_plan_digest",
        "byte_digests",
        "profile_versions",
        "preset_versions",
        "adapter_code_versions",
        "model_versions",
        "consent_state_versions",
        "toolchain_versions",
        "configuration_digest",
        "codec_mux_digest",
        "conversion_digest",
        "capability_manifest",
    ):
        incomplete = dict(payload)
        incomplete.pop(required)
        with pytest.raises(ValidationError):
            FingerprintInputs(**incomplete)


def test_fingerprint_pre_materialization_limit_handles_generators() -> None:
    inputs = _fingerprint_inputs()
    at_limit = ((f"source_{index}", _SHA_A) for index in range(MAX_FINGERPRINT_ITEMS))
    FingerprintInputs(**{**inputs.model_dump(), "byte_digests": at_limit})
    over_limit = ((f"source_{index}", _SHA_A) for index in range(MAX_FINGERPRINT_ITEMS + 1))
    with pytest.raises(ValidationError):
        FingerprintInputs(**{**inputs.model_dump(), "byte_digests": over_limit})


class _CacheLedger:
    def __init__(self, *, deny: bool = False) -> None:
        self.deny = deny
        self.boundaries: list[AuthorizationBoundary] = []

    def authorize(self, boundary: AuthorizationBoundary, **kwargs: object) -> tuple[str, ...]:
        self.boundaries.append(boundary)
        if self.deny:
            raise AuthorizationError("authorization denied", code="grant_revoked")
        return ("grant_a",)

    def resolve_grants(self, asset_id: str) -> tuple[str, ...]:
        if self.deny:
            raise AuthorizationError("authorization denied", code="grant_missing")
        return ("grant_a",)

    def record_asset(self, asset_id: str, **kwargs: object) -> object:
        if self.deny:
            raise AuthorizationError("authorization denied", code="grant_missing")
        return object()

    def commit_lease(self, lease_id: str, **kwargs: object) -> object:
        return object()

    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        if self.deny:
            raise AuthorizationError("authorization denied", code="cloud_egress_denied")
        return ("grant_a",)


def _store(cache: AuthorizationAwareCache, stage: str, artifact: str, ledger: _CacheLedger) -> None:
    cache.store_authorized(
        build_render_fingerprint(_fingerprint_inputs()),
        stage,
        artifact_id=artifact,
        artifact_digest=_SHA_A,
        lineage=AuthorizedLineage(pre_recorded_output=True),
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
    )


def test_cache_store_requires_live_known_lineage_and_reuse_rechecks_immediately() -> None:
    cache = AuthorizationAwareCache()
    with pytest.raises(CacheError) as exc_info:
        _store(cache, "render:cue_001", "asset_001", _CacheLedger(deny=True))
    assert exc_info.value.code == "cache_authorization_denied"
    assert exc_info.value.__cause__ is None
    ledger = _CacheLedger()
    _store(cache, "render:cue_001", "asset_001", ledger)
    with pytest.raises(CacheError) as exc_info:
        cache.reuse_authorized(
            build_render_fingerprint(_fingerprint_inputs()),
            "render:cue_001",
            content_digest=_SHA_A,
            ledger=_CacheLedger(deny=True),
            context=_CONTEXT,
            at_iso=_NOW,
        )
    assert exc_info.value.code == "cache_authorization_denied"


def test_cache_tamper_and_derivative_outcomes_evict_all_aliases() -> None:
    ledger = _CacheLedger()
    cache = AuthorizationAwareCache()
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    _store(cache, "render:cue_001", "asset_shared", ledger)
    _store(cache, "render:cue_002", "asset_shared", ledger)
    key = fingerprint.cache_key("render:cue_001")
    cache._entries[key] = replace(cache._entries[key], fingerprint_digest=_SHA_B)
    with pytest.raises(CacheError) as exc_info:
        cache.reuse_authorized(
            fingerprint,
            "render:cue_001",
            content_digest=_SHA_A,
            ledger=ledger,
            context=_CONTEXT,
            at_iso=_NOW,
        )
    assert exc_info.value.code == "cache_tampered"
    cache.apply_derivative_outcome(
        DerivativeOutcome(
            asset_id="asset_shared",
            grant_id="grant_a",
            disposition=DerivativeDisposition.QUARANTINE,
            at_iso=_NOW,
        )
    )
    assert cache.entry_count == 0


def test_preset_and_cache_capacity_bound_arbitrary_generators() -> None:
    catalog = PresetCatalog(
        Preset(
            preset_id=f"profile_{index}",
            kind=PresetKind.PROFILE,
            version="v1",
            payload=_payload(),
        )
        for index in range(MAX_S3_PRESETS)
    )
    assert catalog.count == MAX_S3_PRESETS
    with pytest.raises(SoundConfigError):
        PresetCatalog(
            Preset(
                preset_id=f"profile_{index}",
                kind=PresetKind.PROFILE,
                version="v1",
                payload=_payload(),
            )
            for index in range(MAX_S3_PRESETS + 1)
        )
    cache = AuthorizationAwareCache(max_entries=MAX_S3_CACHE_ENTRIES)
    ledger = _CacheLedger()
    for index in range(MAX_S3_CACHE_ENTRIES):
        _store(cache, f"render:cue_{index}", f"asset_{index}", ledger)
    with pytest.raises(CacheError) as exc_info:
        _store(cache, "render:cue_overflow", "asset_overflow", ledger)
    assert exc_info.value.code == "cache_capacity_exceeded"
