"""Provider protocols and fake-only remote job mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from .contracts import (
    EgressManifest,
    NetworkApproval,
    RemoteContractError,
    _relative_path,
    assert_network_approval,
)
from .jobs import (
    AdapterKind,
    AdapterMapping,
    ApprovedLocalPlan,
    RemoteExecutionSelection,
    RemoteJobSpec,
)


class ProviderAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    @property
    def kind(self) -> AdapterKind: ...

    def map_approved_plan(self, local_plan: ApprovedLocalPlan, manifest: EgressManifest) -> AdapterMapping: ...


class RenderProviderAdapter(ProviderAdapter, Protocol):
    @property
    def kind(self) -> Literal["render"]: ...


class DeliveryProviderAdapter(ProviderAdapter, Protocol):
    @property
    def kind(self) -> Literal["delivery"]: ...


class HostingProviderAdapter(ProviderAdapter, Protocol):
    @property
    def kind(self) -> Literal["hosting"]: ...


@dataclass(frozen=True)
class FakeRenderAdapter:
    provider: str
    adapter_version: str = "fake-v1"
    kind: Literal["render"] = field(default="render", init=False)

    def map_approved_plan(self, local_plan: ApprovedLocalPlan, manifest: EgressManifest) -> AdapterMapping:
        return AdapterMapping(
            approved_plan=local_plan.plan,
            parameters={
                "operation": "render",
                "egress_files": [item.model_dump(mode="json") for item in manifest.files],
            },
        )


@dataclass(frozen=True)
class FakeDeliveryAdapter:
    provider: str
    destination: str
    adapter_version: str = "fake-v1"
    kind: Literal["delivery"] = field(default="delivery", init=False)

    def __post_init__(self) -> None:
        _relative_path(self.destination)

    def map_approved_plan(self, local_plan: ApprovedLocalPlan, manifest: EgressManifest) -> AdapterMapping:
        return AdapterMapping(
            approved_plan=local_plan.plan,
            parameters={"operation": "delivery", "destination": self.destination},
        )


@dataclass(frozen=True)
class FakeHostingAdapter:
    provider: str
    destination: str
    adapter_version: str = "fake-v1"
    kind: Literal["hosting"] = field(default="hosting", init=False)

    def __post_init__(self) -> None:
        _relative_path(self.destination)

    def map_approved_plan(self, local_plan: ApprovedLocalPlan, manifest: EgressManifest) -> AdapterMapping:
        return AdapterMapping(
            approved_plan=local_plan.plan,
            parameters={"operation": "hosting", "destination": self.destination},
        )


def prepare_remote_job(
    *,
    adapter: ProviderAdapter,
    local_plan: ApprovedLocalPlan,
    manifest: EgressManifest | dict,
    network_approval: NetworkApproval,
    selection: RemoteExecutionSelection,
) -> RemoteJobSpec:
    """Map an explicitly selected, approved local plan without broadening intent."""

    parsed_manifest = manifest if isinstance(manifest, EgressManifest) else EgressManifest.model_validate(manifest)
    assert_network_approval(parsed_manifest, network_approval)
    if adapter.provider != parsed_manifest.location.provider or selection.provider != adapter.provider:
        raise RemoteContractError("adapter provider does not match approved remote selection")
    if adapter.kind != selection.kind:
        raise RemoteContractError("adapter kind does not match explicit remote selection")
    mapping = adapter.map_approved_plan(local_plan.model_copy(deep=True), parsed_manifest.model_copy(deep=True))
    if not isinstance(mapping, AdapterMapping):
        mapping = AdapterMapping.model_validate(mapping)
    if mapping.approved_plan != local_plan.plan:
        raise RemoteContractError("adapter changed creative intent by changing the approved plan")
    reserved = {
        "creative_intent_sha256",
        "creative_approval_sha256",
        "local_plan_sha256",
    }
    if reserved.intersection(mapping.parameters):
        raise RemoteContractError("adapter changed creative intent through reserved parameters")
    return RemoteJobSpec.create(
        provider=adapter.provider,
        adapter_version=adapter.adapter_version,
        kind=adapter.kind,
        local_plan=local_plan,
        egress_manifest_sha256=parsed_manifest.manifest_sha256,
        network_approval_sha256=network_approval.approval_sha256,
        remote_selection_sha256=selection.selection_sha256,
        mapping=mapping,
    )


def select_execution(
    *,
    local_executor: str | None,
    explicit_remote_selection: RemoteExecutionSelection | None,
) -> dict[str, str]:
    """Select local by default; remote is possible only through an explicit selection."""

    if explicit_remote_selection is not None:
        return {
            "mode": "remote",
            **explicit_remote_selection.model_dump(mode="json"),
        }
    if local_executor:
        return {"mode": "local", "executor": local_executor}
    raise RemoteContractError(
        "local executor is unavailable and cloud fallback is disabled; approve remote execution explicitly",
        code="local_executor_unavailable",
    )
