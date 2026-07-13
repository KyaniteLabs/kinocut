"""Final independent-review regressions for S3 trust-boundary closure."""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.provider_policy import (
    CloudExecutionApproval,
    ExecutionPolicy,
    ProviderExecutionLimits,
    select_adapter,
    validate_cloud_approval,
)
from kinocut_sound.registry import AdapterRegistry, RegistryError
from kinocut_sound.s3_cache import AuthorizationAwareCache, AuthorizedLineage, CacheError
from kinocut_sound.s3_fingerprint import build_render_fingerprint

from tests.test_kinocut_sound_s3_policy import (
    _CONTEXT,
    _NOW,
    _SHA_A,
    _SHA_B,
    _Adapter,
    _fingerprint_inputs,
    _ledger,
    _local,
)
from tests.test_kinocut_sound_s3_review import (
    _approved_cloud,
    _cloud_registration,
    _limits,
    _policy,
    _request,
    _route,
)


@pytest.mark.parametrize("adapter_id", ("pkg.module.Adapter", "pkg.module:Adapter", "AdapterClass"))
def test_registry_rejects_import_shaped_ids_without_side_effects(adapter_id: str) -> None:
    calls = 0

    def constructor() -> _Adapter:
        nonlocal calls
        calls += 1
        return _local()

    with pytest.raises(RegistryError) as exc_info:
        AdapterRegistry({adapter_id: constructor})
    assert exc_info.value.code == "invalid_registry"
    assert calls == 0


def test_cloud_approval_requires_internal_issuance_and_exact_snapshot() -> None:
    _, approval, policy = _approved_cloud()
    clone = CloudExecutionApproval(**approval.model_dump(mode="python"))
    with pytest.raises(RegistryError):
        validate_cloud_approval(clone, policy)

    mismatches = (
        {"provider_id": "provider_b"},
        {"region": "eu-west-1"},
        {"egress_host": "api.other.test"},
        {"credential_handle": "rotated_key"},
        {"data_classes": ("other_data",)},
        {"retention_days": 2},
        {"territory": "GB"},
        {"request_digest": _SHA_B},
        {"route_digest": _SHA_B},
        {"policy_digest": _SHA_B},
        {"confirmed": False},
    )
    for update in mismatches:
        with pytest.raises(RegistryError) as exc_info:
            validate_cloud_approval(approval.model_copy(update=update), policy)
        assert exc_info.value.code == "cloud_policy_changed"


def test_cloud_approval_self_validates_policy_without_external_policy() -> None:
    _, approval, policy = _approved_cloud()
    mismatched_policy = policy.model_copy(update={"allow_cloud": False})
    mismatches = (
        {"policy_digest": _SHA_B},
        {"policy_snapshot": mismatched_policy},
    )

    for update in mismatches:
        with pytest.raises(RegistryError) as exc_info:
            validate_cloud_approval(approval.model_copy(update=update))
        assert exc_info.value.code == "cloud_policy_changed"


def test_coherent_model_copy_forgery_loses_internal_issuance_proof() -> None:
    _, approval, policy = _approved_cloud()
    validate_cloud_approval(approval)
    validate_cloud_approval(approval, policy)

    forged_route = approval.route_snapshot.model_copy(
        update={
            "provider_id": "provider_b",
            "region": "eu-west-1",
            "egress_host": "api.other.test",
            "credential_handle": "provider_b_key",
        }
    )
    forged_request = approval.request_snapshot.model_copy(
        update={
            "egress_host": forged_route.egress_host,
            "credential_handle": forged_route.credential_handle,
        }
    )
    forged_policy = approval.policy_snapshot.model_copy(update={"routes": (forged_route,)})
    forged = approval.model_copy(
        update={
            "provider_id": forged_route.provider_id,
            "region": forged_route.region,
            "egress_host": forged_route.egress_host,
            "credential_handle": forged_route.credential_handle,
            "request_snapshot": forged_request,
            "route_snapshot": forged_route,
            "policy_snapshot": forged_policy,
            "request_digest": canonical_digest(forged_request),
            "route_digest": canonical_digest(forged_route),
            "limits_digest": canonical_digest(approval.limits_snapshot),
            "policy_digest": canonical_digest(forged_policy),
        }
    )

    validation_errors: list[str | None] = []
    for expected_policy in (None, forged_policy):
        try:
            validate_cloud_approval(forged, expected_policy)
        except RegistryError as exc:
            validation_errors.append(exc.code)
        else:
            validation_errors.append(None)

    ledger = _ledger()
    ledger.acquire_lease(
        "lease_forged",
        grant_ids=("grant_a",),
        ttl_seconds=30,
        context=_CONTEXT,
        at_iso=_NOW,
        actor_id="actor_a",
    )
    cache_error = None
    try:
        AuthorizationAwareCache().store_authorized(
            build_render_fingerprint(_fingerprint_inputs()),
            "render:forged",
            artifact_id="forged_output",
            artifact_digest=_SHA_A,
            lineage=AuthorizedLineage(lease_id="lease_forged", actor_id="actor_a"),
            ledger=ledger,
            context=_CONTEXT,
            at_iso=_NOW,
            cloud_approval=forged,
        )
    except CacheError as exc:
        cache_error = exc.code

    assert {"validation_errors": validation_errors, "cache_error": cache_error} == {
        "validation_errors": ["cloud_policy_changed", "cloud_policy_changed"],
        "cache_error": "cache_cloud_unconfirmed",
    }


def test_authorized_cache_lease_lineage_uses_real_s2_commit_contract() -> None:
    ledger = _ledger()
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=30,
        context=_CONTEXT,
        at_iso=_NOW,
        actor_id="actor_a",
    )
    cache = AuthorizationAwareCache()
    entry = cache.store_authorized(
        build_render_fingerprint(_fingerprint_inputs()),
        "render:leased",
        artifact_id="lease_output",
        artifact_digest=_SHA_A,
        lineage=AuthorizedLineage(lease_id="lease_a", actor_id="actor_a"),
        ledger=ledger,
        context=_CONTEXT,
        at_iso=_NOW,
    )
    assert entry.grant_ids == ("grant_a",)
    assert ledger.resolve_grants("lease_output") == ("grant_a",)


def test_selection_revalidates_hostile_model_constructs_without_leakage() -> None:
    registry = AdapterRegistry({"tts_cloud": _cloud_registration()})
    marker = "/private/PROVIDER_POLICY_MARKER"

    def unsafe_policy(**updates: object) -> ExecutionPolicy:
        values = {
            "allow_cloud": True,
            "cloud_execution_confirmed": True,
            "routes": (_route(),),
            "limits": _limits(),
            **updates,
        }
        return ExecutionPolicy.model_construct(**values)

    cases = (
        (unsafe_policy(allow_cloud="yes"), _request()),
        (unsafe_policy(routes=(_route().model_copy(update={"confirmed": "yes"}),)), _request()),
        (
            unsafe_policy(limits=_limits().model_copy(update={"max_retries": "2"})),
            _request(),
        ),
        (
            _policy(),
            _request().model_copy(update={"request_is_idempotent": "yes", "retry_class": marker}),
        ),
    )
    for policy, request in cases:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(RegistryError) as exc_info:
                select_adapter(
                    registry,
                    ("tts_cloud",),
                    kind="tts",
                    policy=policy,
                    ledger=_ledger(),
                    request=request,
                )
        assert not caught
        assert marker not in repr(exc_info.value)


def test_provider_resource_ceilings_are_strict_and_bound_into_selection() -> None:
    payload = _limits().model_dump(mode="python")
    for field in ("max_input_bytes", "max_output_bytes", "max_duration_seconds"):
        with pytest.raises(ValidationError):
            ProviderExecutionLimits(**{**payload, field: 0})
        with pytest.raises(ValidationError):
            ProviderExecutionLimits(**{**payload, field: 10**18})
    limits = ProviderExecutionLimits(
        **{
            **payload,
            "max_input_bytes": 1,
            "max_output_bytes": 2,
            "max_duration_seconds": 3.0,
        }
    )
    policy = _policy().model_copy(update={"limits": limits})
    selection = select_adapter(
        AdapterRegistry({"tts_cloud": _cloud_registration()}),
        ("tts_cloud",),
        kind="tts",
        policy=policy,
        ledger=_ledger(),
        request=_request(),
    )
    assert selection.limits_snapshot == limits
    assert selection.cloud_approval is not None
    assert selection.cloud_approval.limits_snapshot == limits
    assert selection.cloud_approval.limits_digest == selection.limits_digest
