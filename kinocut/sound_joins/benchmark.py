"""S14 versioned fixture + cold/warm dual-class benchmark harness."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from kinocut.sound_joins.d41_bind import default_kinocut_d41_port
from kinocut.sound_joins.d42_bind import default_kinocut_d42_port
from kinocut.sound_joins.scheduler import BoundedProcessPool, PoolLimits
from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.mix.renderer import MixClip, MixRenderer
from kinocut_sound.timeline import Cue, CueKind, Timeline
from kinocut_sound.world.d41_port import BedKind, BedSpec

FIXTURE_VERSION = "sound-bench-v1"
DEFAULT_CLIP_COUNT = 64
MAX_MINUTES = 30.0
_SHA = "sha256:" + "b" * 64


@dataclass(frozen=True)
class BenchmarkClass:
    class_id: str
    machine: str
    processor: str
    platform: str


@dataclass(frozen=True)
class FixtureSpec:
    version: str = FIXTURE_VERSION
    clip_count: int = DEFAULT_CLIP_COUNT
    clip_duration_seconds: float = 0.15


@dataclass
class BenchmarkReceipt:
    fixture_version: str
    hardware_class: str
    machine: str
    processor: str
    platform: str
    clip_count: int
    cold_seconds: float
    warm_seconds: float
    cold_ok: bool
    warm_ok: bool
    under_30m: bool
    required_capabilities: dict[str, bool] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    status: str = "ok"

    def to_payload(self) -> dict[str, Any]:
        capability_keys = ("d41_bed", "d41_audition", "d42_style", "d42_identity")
        return {
            "fixture_version": self.fixture_version,
            "hardware_class": self.hardware_class,
            "clip_count": self.clip_count,
            "cold_seconds": self.cold_seconds,
            "warm_seconds": self.warm_seconds,
            "cold_ok": self.cold_ok,
            "warm_ok": self.warm_ok,
            "under_30m": self.under_30m,
            "required_capabilities": {key: bool(self.required_capabilities.get(key, False)) for key in capability_keys},
        }

    def digest(self) -> str:
        body = json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(body).hexdigest()


def detect_benchmark_class() -> BenchmarkClass:
    import platform

    machine = platform.machine().lower()
    system = platform.system().lower()
    if machine in {"arm64", "aarch64"} and system == "darwin":
        class_id = "apple_silicon"
    elif machine in {"x86_64", "amd64"} and system == "linux":
        class_id = "x86_linux"
    else:
        class_id = f"other_{system}_{machine}"
    return BenchmarkClass(
        class_id=class_id,
        machine=platform.machine(),
        processor=platform.processor() or platform.machine(),
        platform=platform.platform(),
    )


def _probe_required() -> dict[str, bool]:
    d41 = default_kinocut_d41_port()
    d42 = default_kinocut_d42_port()
    bed, aud = d41.probe()
    style, ident = d42.probe()
    return {
        "d41_bed": bed.available,
        "d41_audition": aud.available,
        "d42_style": style.available,
        "d42_identity": ident.available,
    }


def _one_clip_work(index: int, duration: float) -> dict[str, Any]:
    wav = synthesize_tone(duration_seconds=duration, seed=index, frequency_hz=220.0 + index)
    cue_id = f"line_{index:03d}"
    timeline = Timeline(
        cues=(
            Cue(
                cue_id=cue_id,
                start_seconds=0.0,
                duration_seconds=duration,
                kind=CueKind.LINE,
                source_ref=f"v/{cue_id}.wav",
            ),
        )
    )
    result = MixRenderer().render(
        timeline=timeline,
        clips=(MixClip(cue_id=cue_id, wav_bytes=wav),),
    )
    port = default_kinocut_d41_port()
    bed = port.bed.prepare_bed(
        BedSpec(
            bed_id=f"bed_{index:03d}",
            kind=BedKind.AMBIENT_BED,
            description_hash=_SHA,
            duration_seconds=duration,
        )
    )
    return {
        "cue_id": cue_id,
        "within_tolerance": result.within_tolerance,
        "bed_hash": bed.descriptor_hash,
        "wav_sha": "sha256:" + hashlib.sha256(wav).hexdigest(),
    }


def _run_fixture(spec: FixtureSpec, *, max_workers: int = 4) -> tuple[float, bool, list[Any]]:
    pool = BoundedProcessPool(
        limits=PoolLimits(
            max_workers=max_workers,
            max_tasks=max(spec.clip_count, 1),
            max_wall_seconds=MAX_MINUTES * 60.0,
        )
    )
    tasks = [
        (
            f"clip_{i:03d}",
            lambda i=i: _one_clip_work(i, spec.clip_duration_seconds),
        )
        for i in range(spec.clip_count)
    ]
    t0 = time.perf_counter()
    results = pool.map_tasks(tasks)
    elapsed = time.perf_counter() - t0
    ok = all(r.ok for r in results) and len(results) >= spec.clip_count
    return elapsed, ok, results


def run_cold_warm_benchmark(
    *,
    fixture: FixtureSpec | None = None,
    max_workers: int = 4,
) -> BenchmarkReceipt:
    fixture = fixture or FixtureSpec()
    hw = detect_benchmark_class()
    caps = _probe_required()
    if not all(caps.values()):
        return BenchmarkReceipt(
            fixture_version=fixture.version,
            hardware_class=hw.class_id,
            machine=hw.machine,
            processor=hw.processor,
            platform=hw.platform,
            clip_count=fixture.clip_count,
            cold_seconds=0.0,
            warm_seconds=0.0,
            cold_ok=False,
            warm_ok=False,
            under_30m=False,
            required_capabilities=caps,
            notes=("required_capabilities_missing",),
            status="failed",
        )

    cold_s, cold_ok, _ = _run_fixture(fixture, max_workers=max_workers)
    warm_s, warm_ok, _ = _run_fixture(fixture, max_workers=max_workers)
    under = (cold_s < MAX_MINUTES * 60.0) and (warm_s < MAX_MINUTES * 60.0)
    status = "ok" if cold_ok and warm_ok and under else "failed"
    return BenchmarkReceipt(
        fixture_version=fixture.version,
        hardware_class=hw.class_id,
        machine=hw.machine,
        processor=hw.processor,
        platform=hw.platform,
        clip_count=fixture.clip_count,
        cold_seconds=round(cold_s, 4),
        warm_seconds=round(warm_s, 4),
        cold_ok=cold_ok,
        warm_ok=warm_ok,
        under_30m=under,
        required_capabilities=caps,
        notes=(),
        status=status,
    )
