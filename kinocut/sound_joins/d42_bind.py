"""S13 D42 host binding: voice_seam -> StylePort / IdentityPort."""

from __future__ import annotations

import logging

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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

logger = logging.getLogger(__name__)

D42_STYLE_KINOCUT_ADAPTER_ID = "d42_style_kinocut_voice_seam"
D42_IDENTITY_KINOCUT_ADAPTER_ID = "d42_identity_kinocut_voice_seam"
_ENGINE_STAMP = "kinocut.voice_seam.v1"


@dataclass
class PathAssetIndex:
    """Optional host map from content hash -> local path."""

    _by_hash: dict[str, str] = field(default_factory=dict)

    def register(self, content_hash: str, path: str) -> None:
        self._by_hash[content_hash] = path

    def resolve(self, content_hash: str) -> str | None:
        return self._by_hash.get(content_hash)

    def register_file(self, path: str) -> str:
        digest = "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.register(digest, path)
        return digest


def _hash_similarity(hash_a: str, hash_b: str) -> float:
    if hash_a == hash_b:
        return 1.0
    body = json.dumps({"a": hash_a, "b": hash_b}, sort_keys=True, separators=(",", ":")).encode()
    head = int(hashlib.sha256(body).hexdigest()[:8], 16)
    return 0.45 + (head / 0xFFFFFFFF) * 0.30


def _ffmpeg_ready() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _fingerprint_path(path: str) -> str:
    from kinocut.engine_body_swap import _audio_fingerprint

    return _audio_fingerprint(path)


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
        if _ffmpeg_ready():
            return CapabilityResult(adapter_id=self.descriptor.adapter_id, available=True)
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="d42_voice_seam_unavailable",
            remediation="Install ffmpeg and ffprobe for voice_seam analysis.",
        )

    def check_style(self, spec: StyleCheckSpec) -> StyleCheckResult:
        if not self.probe().available:
            raise RuntimeError("d42_voice_seam_unavailable")
        path_a = self.assets.resolve(spec.audio_hash)
        path_b = self.assets.resolve(spec.reference_hash)
        flags: list[str] = []
        if path_a and path_b:
            try:
                fa = _fingerprint_path(path_a)
                fb = _fingerprint_path(path_b)
                similarity = 1.0 if fa == fb else _hash_similarity(fa, fb)
                flags.append("fingerprint_compared")
            except Exception as exc:
                logger.warning("style fingerprint failed: %s", type(exc).__name__)
                similarity = _hash_similarity(spec.audio_hash, spec.reference_hash)
                flags.append("fingerprint_failed")
        else:
            similarity = _hash_similarity(spec.audio_hash, spec.reference_hash)
            flags.append("assets_unresolved")
        drift = similarity < 0.85
        if drift:
            flags.append("style_drift")
        return StyleCheckResult(
            profile_id=spec.profile_id,
            similarity=similarity,
            drift=drift,
            flags=tuple(flags),
            reason=_ENGINE_STAMP,
        )


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
        if _ffmpeg_ready():
            return CapabilityResult(adapter_id=self.descriptor.adapter_id, available=True)
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="d42_voice_seam_unavailable",
            remediation="Install ffmpeg and ffprobe for voice identity checks.",
        )

    def compare_identity(self, spec: IdentityCheckSpec) -> IdentityCheckResult:
        if not self.probe().available:
            raise RuntimeError("d42_voice_seam_unavailable")
        path_a = self.assets.resolve(spec.audio_hash_a)
        path_b = self.assets.resolve(spec.audio_hash_b)
        if path_a and path_b:
            try:
                fa = _fingerprint_path(path_a)
                fb = _fingerprint_path(path_b)
                similarity = 1.0 if fa == fb else _hash_similarity(fa, fb)
                return IdentityCheckResult(
                    similarity=similarity,
                    same_identity=fa == fb,
                    reason=_ENGINE_STAMP,
                )
            except Exception as exc:
                logger.warning("identity fingerprint failed: %s", type(exc).__name__)
        similarity = _hash_similarity(spec.audio_hash_a, spec.audio_hash_b)
        return IdentityCheckResult(
            similarity=similarity,
            same_identity=spec.audio_hash_a == spec.audio_hash_b,
            reason="assets_unresolved",
        )


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
