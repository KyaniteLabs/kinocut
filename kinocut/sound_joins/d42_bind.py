"""D42 host ports; semantic voice analysis requires a perceptual backend.

Exact audio stream hashes can verify preservation, but cannot measure speaker
identity or vocal style. The default ports remain unavailable until such a
backend is implemented; test-only fake ports live in kinocut_sound.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from kinocut.errors import MCPVideoError

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.voice_consistency.d42_port import (
    IdentityCheckResult,
    IdentityCheckSpec,
    IdentityPort,
    StyleCheckResult,
    StyleCheckSpec,
    StylePort,
)

D42_STYLE_KINOCUT_ADAPTER_ID = "d42_style_kinocut_voice_seam"
D42_IDENTITY_KINOCUT_ADAPTER_ID = "d42_identity_kinocut_voice_seam"


@dataclass
class PathAssetIndex:
    """Optional host map from content hash -> local path."""

    _by_hash: dict[str, str] = field(default_factory=dict)

    def register(self, content_hash: str, path: str) -> None:
        self._by_hash[content_hash] = path

    def resolve(self, content_hash: str) -> str | None:
        return self._by_hash.get(content_hash)

    def register_file(self, path: str) -> str:
        with Path(path).open("rb") as handle:
            digest = "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()
        self.register(digest, path)
        return digest


def _backend_unavailable(capability: str) -> MCPVideoError:
    return MCPVideoError(
        f"Perceptual voice {capability} analysis has no configured backend. "
        "Audio content hashes cannot establish speaker identity or vocal style.",
        error_type="dependency_error",
        code="d42_voice_seam_unavailable",
        suggested_action={
            "auto_fix": False,
            "description": f"Supply a calibrated perceptual voice {capability} port.",
        },
    )


class KinocutStyleAdapter:
    def __init__(self, assets: PathAssetIndex | None = None) -> None:
        self.assets = assets or PathAssetIndex()
        self.descriptor = AdapterDescriptor(
            adapter_id=D42_STYLE_KINOCUT_ADAPTER_ID,
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="kinocut_voice_seam",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="d42_voice_seam_unavailable",
            remediation="Supply a calibrated perceptual voice style port.",
        )

    def check_style(self, spec: StyleCheckSpec) -> StyleCheckResult:
        raise _backend_unavailable("style")


class KinocutIdentityAdapter:
    def __init__(self, assets: PathAssetIndex | None = None) -> None:
        self.assets = assets or PathAssetIndex()
        self.descriptor = AdapterDescriptor(
            adapter_id=D42_IDENTITY_KINOCUT_ADAPTER_ID,
            kind="analyzer",
            locality=AdapterLocality.LOCAL,
            provider_class="kinocut_voice_seam",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="d42_voice_seam_unavailable",
            remediation="Supply a calibrated perceptual speaker identity port.",
        )

    def compare_identity(self, spec: IdentityCheckSpec) -> IdentityCheckResult:
        raise _backend_unavailable("identity")


@dataclass(frozen=True)
class KinocutD42Port:
    style: StylePort
    identity: IdentityPort

    def probe(self) -> tuple[CapabilityResult, CapabilityResult]:
        return (self.style.probe(), self.identity.probe())


def default_kinocut_d42_port(assets: PathAssetIndex | None = None) -> KinocutD42Port:
    index = assets or PathAssetIndex()
    return KinocutD42Port(
        style=KinocutStyleAdapter(index),
        identity=KinocutIdentityAdapter(index),
    )
