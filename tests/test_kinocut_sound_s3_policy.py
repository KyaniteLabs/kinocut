"""S3 static registry, project policy, fingerprint, and cache acceptance tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.authorization import AuthorizationBoundary, AuthorizationContext, ConsentLedger
from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
    CostDisclosure,
)
from kinocut_sound.consent import (
    CloudEgressGrant,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)
from kinocut_sound.provider_policy import (
    CloudRouteBinding,
    ExecutionPolicy,
    ProviderRequest,
    select_adapter,
)
from kinocut_sound.registry import AdapterRegistration, AdapterRegistry, RegistryError
from kinocut_sound.s3_cache import AuthorizationAwareCache, AuthorizedLineage, CacheError
from kinocut_sound.s3_fingerprint import (
    CapabilityRequirement,
    CapabilitySnapshot,
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

_SHA_A = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_NOW = "2026-07-13T12:00:00Z"
_CONTEXT = AuthorizationContext(
    operation="voice_clone",
    project_id="project_a",
    provider_class="cloud",
    territory="US",
)


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


def _registration(factory: object, descriptor: AdapterDescriptor) -> AdapterRegistration:
    return AdapterRegistration(descriptor=descriptor, constructor=factory)


def _local_registration(factory: object = _local) -> AdapterRegistration:
    return _registration(factory, _local().descriptor)


def _cloud_registration(factory: object = _cloud) -> AdapterRegistration:
    return _registration(factory, _cloud().descriptor)


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
    )
    return base.model_copy(update=updates)


def _cloud_policy(route: CloudRouteBinding | None = None) -> ExecutionPolicy:
    return ExecutionPolicy(
        allow_cloud=True,
        cloud_execution_confirmed=True,
        routes=(route or _route(),),
    )


def _request(**updates: object) -> ProviderRequest:
    base = ProviderRequest(
        egress_host="api.provider.test",
        credential_handle="provider_a_key",
        data_classes=("reference_audio",),
        retention_days=7,
        territory="US",
        grant_ids=("grant_a",),
        context=_CONTEXT,
        at_iso=_NOW,
    )
    return base.model_copy(update=updates)


def _ledger() -> ConsentLedger:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(
        ConsentGrant(
            grant_id="grant_a",
            subject_id="subject_opaque",
            rightsholder_id="rights_opaque",
            scope=ConsentScope(
                project_ids=("project_a",),
                operations=("voice_clone",),
                provider_classes=("cloud",),
                territory="US",
            ),
            reference_evidence_hash=_SHA_A,
            transcript_evidence_hash=_SHA_B,
            reviewer_id="reviewer_a",
            issue_iso="2026-01-01T00:00:00Z",
            expiry_iso="2027-01-01T00:00:00Z",
            state=ConsentState.LIVE,
            retention=RetentionPolicy(
                biometric_retention="quarantine_on_revocation",
                audit_retention="keep_5y",
            ),
            cloud_egress=CloudEgressGrant(
                provider_id="provider_a",
                data_classes=("reference_audio",),
                territory="US",
                retention_ceiling_days=7,
                expiry_iso="2027-01-01T00:00:00Z",
            ),
        ),
        at_iso=_NOW,
        actor_id="reviewer_a",
    )
    return ledger


def _fingerprint_inputs() -> FingerprintInputs:
    return FingerprintInputs(
        normalized_plan_digest=_SHA_A,
        byte_digests=(("source_dialogue", _SHA_A), ("ir_medium_room", _SHA_B)),
        profile_versions=(("profile_narrator", "v1"),),
        preset_versions=(("spatial_medium_room", "v2"),),
        adapter_code_versions=(("tts_local", "sha256:" + "c" * 64),),
        model_versions=(("model_voice", "v3"),),
        consent_state_versions=(("grant_a", "live_r1"),),
        toolchain_versions=(("ffmpeg", "7.1"), ("kinocut_sound", "0.1.0")),
        configuration_digest="sha256:" + "d" * 64,
        codec_mux_digest="sha256:" + "e" * 64,
        conversion_digest="sha256:" + "f" * 64,
        seed="seed_1",
        locale="en_US",
        hardware_backend="cpu_x86_64",
        concurrency_ordering="cue_id_serial",
        capability_manifest=(
            CapabilitySnapshot(
                adapter_id="tts_local",
                available=True,
                probe_version="probe_v1",
                requirement=CapabilityRequirement.REQUIRED,
            ),
        ),
    )


def _payload(digest: str = _SHA_A) -> VerifiedPayloadRef:
    return VerifiedPayloadRef(asset_id="preset_payload", content_digest=digest, verified=True)


def _preset(kind: PresetKind) -> Preset:
    return Preset(
        preset_id=f"{kind.value}_default",
        kind=kind,
        version="v1",
        payload=_payload(),
    )


def _address(kind: PresetKind) -> PresetAddress:
    return PresetAddress(
        preset_id=f"{kind.value}_default",
        kind=kind,
        version="v1",
        expected_digest=_SHA_A,
    )


class _CacheLedger:
    def __init__(self) -> None:
        self.boundaries: list[AuthorizationBoundary] = []
        self.egress_calls = 0

    def authorize(self, boundary: AuthorizationBoundary, **kwargs: object) -> tuple[str, ...]:
        self.boundaries.append(boundary)
        return ("grant_a",)

    def resolve_grants(self, asset_id: str) -> tuple[str, ...]:
        return ("grant_a",)

    def record_asset(self, asset_id: str, **kwargs: object) -> object:
        return object()

    def commit_lease(self, lease_id: str, **kwargs: object) -> object:
        return object()

    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        self.egress_calls += 1
        return ("grant_a",)


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


def test_all_four_preset_kinds_round_trip_by_verified_address() -> None:
    catalog = PresetCatalog()
    for kind in PresetKind:
        preset = _preset(kind)
        catalog.save(preset)
        assert catalog.load(_address(kind)) == preset
    assert {kind.value for kind in PresetKind} == {"profile", "chain", "spatial", "bed"}


def test_project_config_selects_only_exact_presets_and_compiled_adapters() -> None:
    catalog = PresetCatalog(tuple(_preset(kind) for kind in PresetKind))
    config = ProjectSoundConfig(
        project_id="project_a",
        roster_preset=_address(PresetKind.PROFILE),
        ambience_preset=_address(PresetKind.BED),
        loudness_preset="stream_-14",
        spatial_preset=_address(PresetKind.SPATIAL),
        chain_preset=_address(PresetKind.CHAIN),
        adapter_ids=("tts_local",),
    )
    policy = ProjectConfigPolicy(
        project_ids=("project_a",),
        allowed_presets=tuple(_address(kind) for kind in PresetKind),
        loudness_presets=("stream_-14",),
        adapter_ids=("tts_local",),
    )
    registry = AdapterRegistry({"tts_local": _local_registration()})
    policy.authorize(config, catalog=catalog, registry=registry)
    with pytest.raises(SoundConfigError) as exc_info:
        policy.authorize(
            config.model_copy(update={"adapter_ids": ("tts_cloud",)}),
            catalog=catalog,
            registry=registry,
        )
    assert exc_info.value.code == "project_config_denied"


def test_local_first_policy_never_silently_falls_back_to_cloud() -> None:
    registry = AdapterRegistry({"tts_local": _local_registration(), "tts_cloud": _cloud_registration()})
    policy = ExecutionPolicy(allow_cloud=False)
    selected = select_adapter(registry, ("tts_cloud", "tts_local"), kind="tts", policy=policy)
    assert selected.descriptor.adapter_id == "tts_local"
    unavailable_local = AdapterRegistry(
        {
            "tts_local": _local_registration(lambda: _Adapter(_local().descriptor, available=False)),
            "tts_cloud": _cloud_registration(),
        }
    )
    with pytest.raises(RegistryError) as exc_info:
        select_adapter(unavailable_local, ("tts_local", "tts_cloud"), kind="tts", policy=policy)
    assert exc_info.value.code == "local_capability_unavailable"


def test_cloud_selection_requires_exact_route_and_s2_authorization() -> None:
    registry = AdapterRegistry({"tts_cloud": _cloud_registration()})
    policy = _cloud_policy()
    selected = select_adapter(
        registry,
        ("tts_cloud",),
        kind="tts",
        policy=policy,
        ledger=_ledger(),
        request=_request(),
    )
    assert selected.descriptor.adapter_id == "tts_cloud"
    assert selected.cloud_approval is not None
    with pytest.raises(RegistryError) as exc_info:
        select_adapter(registry, ("tts_cloud",), kind="tts", policy=policy)
    assert exc_info.value.code == "cloud_authorization_required"


def test_full_fingerprint_and_cache_keys_invalidate_every_bound_dimension() -> None:
    base_inputs = _fingerprint_inputs()
    base = build_render_fingerprint(base_inputs)
    assert base.cache_key("render:cue_001") != base.cache_key("render:cue_002")
    mutations = (
        {"normalized_plan_digest": _SHA_B},
        {"byte_digests": (("source_dialogue", _SHA_B),)},
        {"profile_versions": (("profile_narrator", "v2"),)},
        {"preset_versions": (("spatial_medium_room", "v3"),)},
        {"adapter_code_versions": (("tts_local", _SHA_B),)},
        {"model_versions": (("model_voice", "v4"),)},
        {"consent_state_versions": (("grant_a", "revoked_r2"),)},
        {"toolchain_versions": (("ffmpeg", "8.0"),)},
        {"configuration_digest": _SHA_B},
        {"codec_mux_digest": _SHA_B},
        {"conversion_digest": _SHA_B},
        {
            "capability_manifest": (
                CapabilitySnapshot(
                    adapter_id="tts_local",
                    available=False,
                    probe_version="probe_v2",
                    requirement=CapabilityRequirement.ADVISORY,
                ),
            )
        },
    )
    for update in mutations:
        changed = build_render_fingerprint(base_inputs.model_copy(update=update))
        assert changed.digest() != base.digest(), update


def test_authorized_cache_rechecks_grants_and_binds_content() -> None:
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    cache = AuthorizationAwareCache()
    ledger = _CacheLedger()
    cache.store_authorized(
        fingerprint,
        "render:cue_001",
        artifact_id="cache_asset_001",
        artifact_digest=_SHA_A,
        lineage=AuthorizedLineage(pre_recorded_output=True),
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
    )
    hit = cache.reuse_authorized(
        fingerprint,
        "render:cue_001",
        content_digest=_SHA_A,
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
    )
    assert hit.artifact_id == "cache_asset_001"
    changed = build_render_fingerprint(_fingerprint_inputs().model_copy(update={"configuration_digest": _SHA_B}))
    with pytest.raises(CacheError) as exc_info:
        cache.reuse_authorized(
            changed,
            "render:cue_001",
            content_digest=_SHA_A,
            ledger=ledger,
            context=_CONTEXT,
            at_iso=_NOW,
        )
    assert exc_info.value.code == "cache_miss"


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


def test_cloud_cache_reuse_rechecks_cache_boundary_and_exact_egress() -> None:
    policy = _cloud_policy()
    selection = select_adapter(
        AdapterRegistry({"tts_cloud": _cloud_registration()}),
        ("tts_cloud",),
        kind="tts",
        policy=policy,
        ledger=_ledger(),
        request=_request(),
    )
    ledger = _CacheLedger()
    fingerprint = build_render_fingerprint(_fingerprint_inputs())
    cache = AuthorizationAwareCache()
    cache.store_authorized(
        fingerprint,
        "render:cue_cloud",
        artifact_id="cache_asset_cloud",
        artifact_digest=_SHA_A,
        lineage=AuthorizedLineage(pre_recorded_output=True),
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
        cloud_approval=selection.cloud_approval,
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
    assert ledger.boundaries == [AuthorizationBoundary.CACHE_REUSE]
    assert ledger.egress_calls == 1
