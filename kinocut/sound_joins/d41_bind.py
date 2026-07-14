"""S13 D41 host binding: audio_bed -> neutral BedPort / AuditionPort."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.world.d41_port import (
    AuditionPort,
    AuditionReelResult,
    BedDescriptor,
    BedPort,
    BedSpec,
    Sha256,
)

D41_BED_KINOCUT_ADAPTER_ID = "d41_bed_kinocut_audio_bed"
D41_AUDITION_KINOCUT_ADAPTER_ID = "d41_audition_kinocut"
_ENGINE_STAMP = "kinocut.engine_audio_bed.v1"


def _hash_payload(payload: dict[str, object]) -> Sha256:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _ffmpeg_ready() -> bool:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    from kinocut.engine_runtime_utils import _check_filter_available

    return bool(_check_filter_available("sidechaincompress") and _check_filter_available("loudnorm"))


class KinocutBedAdapter:
    """Real D41 bed adapter bound to audio_bed capability."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id=D41_BED_KINOCUT_ADAPTER_ID,
            kind="asset",
            locality=AdapterLocality.LOCAL,
            provider_class="kinocut_audio_bed",
        )

    def probe(self) -> CapabilityResult:
        if _ffmpeg_ready():
            return CapabilityResult(adapter_id=self.descriptor.adapter_id, available=True)
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=False,
            reason_code="d41_audio_bed_unavailable",
            remediation="Install ffmpeg with sidechaincompress and loudnorm filters.",
        )

    def prepare_bed(self, spec: BedSpec) -> BedDescriptor:
        if not self.probe().available:
            raise RuntimeError("d41_audio_bed_unavailable")
        descriptor_hash = _hash_payload(
            {
                "adapter_id": D41_BED_KINOCUT_ADAPTER_ID,
                "engine": _ENGINE_STAMP,
                "bed_id": spec.bed_id,
                "kind": spec.kind.value,
                "description_hash": spec.description_hash,
                "duration_seconds": spec.duration_seconds,
            }
        )
        return BedDescriptor(
            bed_id=spec.bed_id,
            descriptor_hash=descriptor_hash,
            duration_seconds=spec.duration_seconds,
        )

    def prepare_bed_from_sources(
        self,
        spec: BedSpec,
        *,
        voice_source: str,
        music_path: str,
        output_path: str,
        **audio_bed_kwargs: Any,
    ) -> BedDescriptor:
        if not self.probe().available:
            raise RuntimeError("d41_audio_bed_unavailable")
        from kinocut.engine_audio_bed import audio_bed

        receipt = audio_bed(voice_source, music_path, output_path, **audio_bed_kwargs)
        out = Path(output_path)
        digest = hashlib.sha256(out.read_bytes()).hexdigest() if out.is_file() else "missing"
        descriptor_hash = _hash_payload(
            {
                "adapter_id": D41_BED_KINOCUT_ADAPTER_ID,
                "engine": _ENGINE_STAMP,
                "bed_id": spec.bed_id,
                "kind": spec.kind.value,
                "description_hash": spec.description_hash,
                "duration_seconds": spec.duration_seconds,
                "output_sha256": f"sha256:{digest}",
                "receipt_keys": sorted(str(k) for k in (receipt or {})),
            }
        )
        return BedDescriptor(
            bed_id=spec.bed_id,
            descriptor_hash=descriptor_hash,
            duration_seconds=spec.duration_seconds,
        )


class KinocutAuditionAdapter:
    """Real D41 audition adapter — perceptual QA, always human-review."""

    def __init__(self) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id=D41_AUDITION_KINOCUT_ADAPTER_ID,
            kind="asset",
            locality=AdapterLocality.LOCAL,
            provider_class="kinocut_bed_audition",
        )

    def probe(self) -> CapabilityResult:
        return CapabilityResult(adapter_id=self.descriptor.adapter_id, available=True)

    def build_audition_reel(
        self,
        *,
        bed_id: str,
        reel_label: str,
        description_hash: Sha256,
    ) -> AuditionReelResult:
        reel_hash = _hash_payload(
            {
                "adapter_id": D41_AUDITION_KINOCUT_ADAPTER_ID,
                "engine": _ENGINE_STAMP,
                "bed_id": bed_id,
                "reel_label": reel_label,
                "description_hash": description_hash,
            }
        )
        return AuditionReelResult(
            bed_id=bed_id,
            reel_label=reel_label,
            reel_hash=reel_hash,
            human_review_required=True,
        )


@dataclass(frozen=True)
class KinocutD41Port:
    bed: BedPort
    audition: AuditionPort

    def probe(self) -> tuple[CapabilityResult, CapabilityResult]:
        return (self.bed.probe(), self.audition.probe())


def default_kinocut_d41_port() -> KinocutD41Port:
    return KinocutD41Port(bed=KinocutBedAdapter(), audition=KinocutAuditionAdapter())
