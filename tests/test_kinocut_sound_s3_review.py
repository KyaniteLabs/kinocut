"""Independent-review regressions for the complete S3 trust boundaries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest
from pydantic import ValidationError

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    DerivativeDisposition,
    DerivativeOutcome,
)
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.limits import (
    MAX_FINGERPRINT_ITEMS,
    MAX_PROVIDER_CONCURRENCY,
    MAX_PROVIDER_RETRIES,
    MAX_S3_REGISTRY_ADAPTERS,
)
from kinocut_sound.provider_policy import (
    CloudExecutionApproval,
    CloudRouteBinding,
    ExecutionPolicy,
    ProviderExecutionLimits,
    ProviderRequest,
    select_adapter,
)
from kinocut_sound.registry import (
    AdapterRegistration,
    AdapterRegistry,
    RegistryError,
)
from kinocut_sound.render_fingerprint import (
    DeterminismClass,
    FingerprintComponent,
    RenderFingerprint,
)
from kinocut_sound.s3_cache import (
    AuthorizationAwareCache,
    AuthorizedLineage,
    CacheError,
)
from kinocut_sound.s3_fingerprint import (
    CapabilityRequirement,
    CapabilitySnapshot,
    FingerprintError,
    FingerprintInputs,
    build_render_fingerprint,
)
from kinocut_sound.sound_config import (
    Preset,
    PresetAddress,
    PresetCatalog,
    PresetKind,
    ProjectConfigPolicy,
    ProjectSoundConfig,
    SoundConfigError,
    VerifiedPayloadRef,
)

from tests.test_kinocut_sound_s3_policy import (
    _CONTEXT,
    _NOW,
    _SHA_A,
    _SHA_B,
    _Adapter,
    _cloud,
    _fingerprint_inputs,
    _ledger,
    _local,
)


def _registration(factory: object, descriptor: AdapterDescriptor) -> AdapterRegistration:
    return AdapterRegistration(descriptor=descriptor, constructor=factory)


def _local_registration(factory: object = _local) -> AdapterRegistration:
    return _registration(factory, _local().descriptor)


def _cloud_registration(factory: object = _cloud) -> AdapterRegistration:
    return _registration(factory, _cloud().descriptor)


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


def _limits(**updates: object) -> ProviderExecutionLimits:
    base = ProviderExecutionLimits(
        connect_timeout_seconds=5.0,
        read_timeout_seconds=30.0,
        total_timeout_seconds=60.0,
        cancellation_required=True,
        max_retries=2,
        transient_idempotent_retries_only=True,
        idempotency_key_required=True,
        max_concurrency=2,
        rate_limit_per_minute=30,
        redirects_allowed=False,
    )
    return base.model_copy(update=updates)


def _route(**updates: object) -> CloudRouteBinding:
    base = CloudRouteBinding(
        provider_id="provider_a",
        region="us-east-1",
        egress_host="api.provider.test",
        credential_handle="provider_a_key",
        data_classes=("reference_audio",),
        retention_ceiling_days=7,
        estimated_cost_ceiling_usd=0.2,
        confirmed=True,
        redirect_hosts=(),
    )
    return base.model_copy(update=updates)


def _policy(*routes: CloudRouteBinding) -> ExecutionPolicy:
    return ExecutionPolicy(
        allow_cloud=True,
        cloud_execution_confirmed=True,
        routes=routes or (_route(),),
        limits=_limits(),
    )


def _request(**updates: object) -> ProviderRequest:
    base = ProviderRequest(
        egress_host="api.provider.test",
        credential_handle="provider_a_key",
        data_classes=("reference_audio",),
        retention_days=3,
        territory="US",
        grant_ids=("grant_a",),
        context=_CONTEXT,
        at_iso=_NOW,
        idempotency_key="request_001",
        request_is_idempotent=True,
        retry_class="transient",
        redirect_host=None,
    )
    return base.model_copy(update=updates)


def test_local_selection_does_not_construct_cloud_candidate() -> None:
    cloud_calls = 0

    def cloud_factory() -> _Adapter:
        nonlocal cloud_calls
        cloud_calls += 1
        return _cloud()

    registry = AdapterRegistry(
        {
            "tts_cloud": _cloud_registration(cloud_factory),
            "tts_local": _local_registration(),
        }
    )
    selected = select_adapter(
        registry,
        ("tts_cloud", "tts_local"),
        kind="tts",
        policy=ExecutionPolicy(allow_cloud=False, limits=_limits()),
    )
    assert selected.descriptor.locality is AdapterLocality.LOCAL
    assert cloud_calls == 0


def test_cloud_route_is_provider_scoped_not_cross_product() -> None:
    routes = (
        _route(),
        _route(
            provider_id="provider_b",
            region="eu-west-1",
            egress_host="api.other.test",
            credential_handle="provider_b_key",
        ),
    )
    hybrid = _request(
        egress_host="api.other.test",
        credential_handle="provider_b_key",
    )
    with pytest.raises(RegistryError) as exc_info:
        select_adapter(
            AdapterRegistry({"tts_cloud": _cloud_registration()}),
            ("tts_cloud",),
            kind="tts",
            policy=_policy(*routes),
            ledger=_ledger(),
            request=hybrid,
        )
    assert exc_info.value.code == "cloud_execution_denied"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("allow_cloud", 1),
        ("cloud_execution_confirmed", 1),
    ),
)
def test_execution_policy_booleans_are_strict(field: str, value: object) -> None:
    payload = {
        "allow_cloud": True,
        "cloud_execution_confirmed": True,
        "routes": (_route(),),
        "limits": _limits(),
        field: value,
    }
    with pytest.raises(ValidationError):
        ExecutionPolicy(**payload)


def test_execution_limits_are_bounded_and_redirects_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ProviderExecutionLimits(
            **{
                **_limits().model_dump(),
                "max_retries": MAX_PROVIDER_RETRIES + 1,
            }
        )
    with pytest.raises(ValidationError):
        ProviderExecutionLimits(
            **{
                **_limits().model_dump(),
                "max_concurrency": MAX_PROVIDER_CONCURRENCY + 1,
            }
        )
    with pytest.raises(RegistryError):
        select_adapter(
            AdapterRegistry({"tts_cloud": _cloud_registration()}),
            ("tts_cloud",),
            kind="tts",
            policy=_policy(),
            ledger=_ledger(),
            request=_request(redirect_host="redirect.provider.test"),
        )


def _approved_cloud() -> tuple[object, CloudExecutionApproval, ExecutionPolicy]:
    policy = _policy()
    selection = select_adapter(
        AdapterRegistry({"tts_cloud": _cloud_registration()}),
        ("tts_cloud",),
        kind="tts",
        policy=policy,
        ledger=_ledger(),
        request=_request(),
    )
    assert selection.cloud_approval is not None
    return selection, selection.cloud_approval, policy


class _CacheSpy:
    def __init__(self, *, grants: tuple[str, ...] = ("grant_a",)) -> None:
        self.grants = grants
        self.boundaries: list[AuthorizationBoundary] = []
        self.egress: list[dict[str, object]] = []

    def authorize(self, boundary: AuthorizationBoundary, **kwargs: object) -> tuple[str, ...]:
        self.boundaries.append(boundary)
        return self.grants

    def resolve_grants(self, asset_id: str) -> tuple[str, ...]:
        return self.grants

    def record_asset(self, asset_id: str, **kwargs: object) -> object:
        return object()

    def commit_lease(self, lease_id: str, **kwargs: object) -> object:
        return object()

    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        self.egress.append(dict(kwargs))
        return self.grants


def test_cloud_cache_binds_original_approval_and_rechecks_exact_scope() -> None:
    _, approval, policy = _approved_cloud()
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    ledger = _CacheSpy()
    cache = AuthorizationAwareCache()
    cache.store_authorized(
        fingerprint,
        "render:cue_cloud",
        artifact_id="cache_cloud",
        artifact_digest=_SHA_A,
        lineage=AuthorizedLineage(pre_recorded_output=True),
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
        cloud_approval=approval,
    )
    cache.reuse_authorized(
        fingerprint,
        "render:cue_cloud",
        content_digest=_SHA_A,
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
        execution_policy=policy,
    )
    assert ledger.boundaries[-1] is AuthorizationBoundary.CACHE_REUSE
    assert ledger.egress[-1]["provider_id"] == "provider_a"
    assert ledger.egress[-1]["data_classes"] == ("reference_audio",)
    assert ledger.egress[-1]["retention_days"] == 3
    assert ledger.egress[-1]["territory"] == "US"

    changed = _policy(_route(credential_handle="rotated_key"))
    with pytest.raises(CacheError) as exc_info:
        cache.reuse_authorized(
            fingerprint,
            "render:cue_cloud",
            content_digest=_SHA_A,
            ledger=ledger,
            context=_CONTEXT,
            at_iso=_NOW,
            execution_policy=changed,
        )
    assert exc_info.value.code == "cache_cloud_policy_changed"


def test_cloud_cache_rejects_unconfirmed_approval() -> None:
    _, approval, _ = _approved_cloud()
    unconfirmed = approval.model_copy(update={"confirmed": False})
    with pytest.raises(CacheError):
        AuthorizationAwareCache().store_authorized(
            build_render_fingerprint(_fingerprint_inputs()),
            "render:cue_cloud",
            artifact_id="cache_cloud",
            artifact_digest=_SHA_A,
            lineage=AuthorizedLineage(pre_recorded_output=True),
            ledger=_CacheSpy(),
            context=_CONTEXT,
            at_iso=_NOW,
            cloud_approval=unconfirmed,
        )


def test_cache_rejects_role_spoofed_partial_fingerprint() -> None:
    spoof = RenderFingerprint(
        determinism_class=DeterminismClass.SIGNAL_EQUIVALENT,
        seed="seed",
        locale="en_US",
        hardware_backend="cpu",
        concurrency_ordering="serial",
        components=tuple(
            FingerprintComponent(role=role, digest=_SHA_A)
            for role in (
                "plan_normalized",
                "bytes_manifest",
                "profile_versions",
                "preset_versions",
                "adapter_code_versions",
                "model_versions",
                "consent_state_versions",
                "config_normalized",
                "codec_mux",
                "conversions",
                "capability_manifest",
            )
        ),
    )
    with pytest.raises(CacheError) as exc_info:
        AuthorizationAwareCache().store_unprotected(
            spoof,
            "render:cue_001",
            artifact_id="asset_001",
            artifact_digest=_SHA_A,
        )
    assert exc_info.value.code == "incomplete_render_fingerprint"


def test_required_and_advisory_fingerprint_classification_is_enforced() -> None:
    inputs = _fingerprint_inputs()
    unavailable_required = inputs.model_copy(
        update={
            "capability_manifest": (
                CapabilitySnapshot(
                    adapter_id="tts_local",
                    available=False,
                    probe_version="probe_v1",
                    requirement=CapabilityRequirement.REQUIRED,
                ),
            )
        }
    )
    with pytest.raises(FingerprintError):
        build_render_fingerprint(unavailable_required)

    advisory = inputs.model_copy(
        update={
            "capability_manifest": (
                CapabilitySnapshot(
                    adapter_id="tts_local",
                    available=True,
                    probe_version="probe_v1",
                    requirement=CapabilityRequirement.REQUIRED,
                ),
                CapabilitySnapshot(
                    adapter_id="analyzer_optional",
                    available=False,
                    probe_version="probe_v1",
                    requirement=CapabilityRequirement.ADVISORY,
                ),
            )
        }
    )
    complete = build_render_fingerprint(advisory)
    assert complete.required_capability_manifest == ("tts_local",)
    assert "analyzer_optional" not in complete.required_capability_manifest


@pytest.mark.parametrize("field", ("toolchain_versions", "capability_manifest"))
def test_fingerprint_bounds_toolchains_and_capabilities_before_materialization(field: str) -> None:
    inputs = _fingerprint_inputs()
    if field == "toolchain_versions":
        oversized = ((f"tool_{index}", "v1") for index in range(MAX_FINGERPRINT_ITEMS + 1))
    else:
        oversized = (
            CapabilitySnapshot(
                adapter_id=f"adapter_{index}",
                available=True,
                probe_version="v1",
                requirement=CapabilityRequirement.ADVISORY,
            )
            for index in range(MAX_FINGERPRINT_ITEMS + 1)
        )
    with pytest.raises(ValidationError):
        FingerprintInputs(**{**inputs.model_dump(), field: oversized})


def test_cache_store_modes_require_trusted_lineage_and_content_digest() -> None:
    cache = AuthorizationAwareCache()
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    cache.store_unprotected(
        fingerprint,
        "render:public",
        artifact_id="public_asset",
        artifact_digest=_SHA_A,
    )
    assert (
        cache.reuse_unprotected(
            fingerprint,
            "render:public",
            content_digest=_SHA_A,
        ).artifact_id
        == "public_asset"
    )
    with pytest.raises(CacheError) as exc_info:
        cache.reuse_unprotected(fingerprint, "render:public", content_digest=_SHA_B)
    assert exc_info.value.code == "cache_content_mismatch"

    with pytest.raises(CacheError) as exc_info:
        cache.store_authorized(
            fingerprint,
            "render:protected",
            artifact_id="protected_asset",
            artifact_digest=_SHA_A,
            lineage=AuthorizedLineage(),
            ledger=_CacheSpy(),
            context=_CONTEXT,
            at_iso=_NOW,
        )
    assert exc_info.value.code == "trusted_lineage_required"


def test_authorized_cache_parent_lineage_and_outcome_evict_all_aliases() -> None:
    cache = AuthorizationAwareCache()
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    ledger = _CacheSpy()
    lineage = AuthorizedLineage(parent_asset_ids=("trusted_parent",))
    for cue in ("render:cue_001", "render:cue_002"):
        cache.store_authorized(
            fingerprint,
            cue,
            artifact_id="shared_asset",
            artifact_digest=_SHA_A,
            lineage=lineage,
            ledger=ledger,
            context=_CONTEXT,
            at_iso=_NOW,
        )
    cache.apply_derivative_outcome(
        DerivativeOutcome(
            asset_id="shared_asset",
            grant_id="grant_a",
            disposition=DerivativeDisposition.DELETE,
            at_iso=_NOW,
        )
    )
    assert cache.entry_count == 0


def _payload(digest: str = _SHA_A, *, verified: bool = True) -> VerifiedPayloadRef:
    return VerifiedPayloadRef(
        asset_id="preset_payload",
        content_digest=digest,
        verified=verified,
    )


def _preset(kind: PresetKind, version: str, digest: str = _SHA_A) -> Preset:
    return Preset(
        preset_id=f"{kind.value}_default",
        kind=kind,
        version=version,
        payload=_payload(digest),
    )


def _address(kind: PresetKind, version: str, digest: str = _SHA_A) -> PresetAddress:
    return PresetAddress(
        preset_id=f"{kind.value}_default",
        kind=kind,
        version=version,
        expected_digest=digest,
    )


def test_preset_catalog_preserves_versions_and_verifies_expected_digest() -> None:
    catalog = PresetCatalog((_preset(PresetKind.PROFILE, "v1"), _preset(PresetKind.PROFILE, "v2", _SHA_B)))
    assert catalog.load(_address(PresetKind.PROFILE, "v1")).version == "v1"
    assert catalog.load(_address(PresetKind.PROFILE, "v2", _SHA_B)).version == "v2"
    with pytest.raises(SoundConfigError) as exc_info:
        catalog.load(_address(PresetKind.PROFILE, "v2", _SHA_A))
    assert exc_info.value.code == "preset_digest_mismatch"
    with pytest.raises(ValidationError):
        VerifiedPayloadRef(asset_id="payload", content_digest=_SHA_A, verified=False)


def test_project_config_resolves_exact_catalog_refs_and_compiled_registry() -> None:
    presets = (
        _preset(PresetKind.PROFILE, "v1"),
        _preset(PresetKind.BED, "v1"),
        _preset(PresetKind.SPATIAL, "v1"),
        _preset(PresetKind.CHAIN, "v1"),
    )
    catalog = PresetCatalog(presets)
    config = ProjectSoundConfig(
        project_id="project_a",
        roster_preset=_address(PresetKind.PROFILE, "v1"),
        ambience_preset=_address(PresetKind.BED, "v1"),
        loudness_preset="stream_-14",
        spatial_preset=_address(PresetKind.SPATIAL, "v1"),
        chain_preset=_address(PresetKind.CHAIN, "v1"),
        adapter_ids=("tts_local",),
    )
    policy = ProjectConfigPolicy(
        project_ids=("project_a",),
        allowed_presets=tuple(
            _address(kind, "v1") for kind in (PresetKind.PROFILE, PresetKind.BED, PresetKind.SPATIAL, PresetKind.CHAIN)
        ),
        loudness_presets=("stream_-14",),
        adapter_ids=("tts_local",),
    )
    policy.authorize(
        config,
        catalog=catalog,
        registry=AdapterRegistry({"tts_local": _local_registration()}),
    )
    with pytest.raises(SoundConfigError):
        policy.authorize(
            config,
            catalog=catalog,
            registry=AdapterRegistry(
                {
                    "tts_other": AdapterRegistration(
                        descriptor=_local("tts_other").descriptor,
                        constructor=lambda: _local("tts_other"),
                    )
                }
            ),
        )
