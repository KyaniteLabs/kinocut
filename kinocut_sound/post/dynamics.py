"""Dynamic compression adapter — reduces loudness range (LRA).

Uses ffmpeg's ``acompressor`` filter with threshold (dB), ratio, attack (ms),
release (ms), and optional makeup gain (dB). The threshold is accepted in dB
and converted to the linear amplitude that ffmpeg expects.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.limits import (
    MAX_POST_DYNAMICS_ATTACK_MS as MAX_ATTACK_MS,
    MAX_POST_DYNAMICS_MAKEUP_DB as MAX_MAKEUP_DB,
    MAX_POST_DYNAMICS_RATIO as MAX_RATIO,
    MAX_POST_DYNAMICS_RELEASE_MS as MAX_RELEASE_MS,
    MAX_POST_DYNAMICS_THRESHOLD_DB as MAX_THRESHOLD_DB,
    MIN_POST_DYNAMICS_ATTACK_MS as MIN_ATTACK_MS,
    MIN_POST_DYNAMICS_MAKEUP_DB as MIN_MAKEUP_DB,
    MIN_POST_DYNAMICS_RATIO as MIN_RATIO,
    MIN_POST_DYNAMICS_RELEASE_MS as MIN_RELEASE_MS,
    MIN_POST_DYNAMICS_THRESHOLD_DB as MIN_THRESHOLD_DB,
)
from kinocut_sound.post._errors import POST_DEPENDENCY_MISSING, PostError
from kinocut_sound.post._subprocess import (
    DEFAULT_POST_TIMEOUT_SECONDS,
    bounded_float,
    ffmpeg_filter_number,
    resolve_binary,
    run_ffmpeg,
)
from kinocut_sound.post.chain import PostContext, PostStageResult
from kinocut_sound.render_fingerprint import DeterminismClass


class DynamicsAdapter:
    """Dynamic range compression via ffmpeg ``acompressor``."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="dynamics_compressor",
            kind="processor",
            locality=AdapterLocality.LOCAL,
            provider_class="ffmpeg",
            timeout_seconds=timeout_seconds,
        )

    def probe(self) -> CapabilityResult:
        try:
            resolve_binary("ffmpeg")
        except PostError:
            return CapabilityResult(
                adapter_id=self.descriptor.adapter_id,
                available=False,
                reason_code=POST_DEPENDENCY_MISSING,
                remediation="Install ffmpeg to enable dynamic compression",
            )
        return CapabilityResult(
            adapter_id=self.descriptor.adapter_id,
            available=True,
        )

    def process(
        self,
        input_path: Path,
        output_path: Path,
        *,
        ctx: PostContext,
        params: Mapping[str, object] | None = None,
    ) -> PostStageResult:
        p = dict(params or {})
        threshold_db = bounded_float(
            p.get("threshold_db", -20.0),
            lo=MIN_THRESHOLD_DB,
            hi=MAX_THRESHOLD_DB,
            name="threshold_db",
        )
        ratio = bounded_float(
            p.get("ratio", 4.0),
            lo=MIN_RATIO,
            hi=MAX_RATIO,
            name="ratio",
        )
        attack_ms = bounded_float(
            p.get("attack_ms", 5.0),
            lo=MIN_ATTACK_MS,
            hi=MAX_ATTACK_MS,
            name="attack_ms",
        )
        release_ms = bounded_float(
            p.get("release_ms", 50.0),
            lo=MIN_RELEASE_MS,
            hi=MAX_RELEASE_MS,
            name="release_ms",
        )
        makeup_db = bounded_float(
            p.get("makeup_db", 0.0),
            lo=MIN_MAKEUP_DB,
            hi=MAX_MAKEUP_DB,
            name="makeup_db",
        )
        # acompressor expects linear threshold and makeup amplitude.
        threshold_linear = 10.0 ** (threshold_db / 20.0)
        makeup_linear = 10.0 ** (makeup_db / 20.0)
        filt = (
            f"acompressor="
            f"threshold={ffmpeg_filter_number(threshold_linear, digits=6)}"
            f":ratio={ffmpeg_filter_number(ratio)}"
            f":attack={ffmpeg_filter_number(attack_ms)}"
            f":release={ffmpeg_filter_number(release_ms)}"
            f":makeup={ffmpeg_filter_number(makeup_linear, digits=6)}"
        )
        run_ffmpeg(
            [
                "-i",
                str(input_path),
                "-af",
                filt,
                "-ar",
                str(ctx.sample_rate_hz),
                "-ac",
                str(ctx.channel_count),
                str(output_path),
            ],
            timeout=self.descriptor.timeout_seconds,
        )
        return PostStageResult(
            adapter_id=self.descriptor.adapter_id,
            output_path=Path(output_path),
            applied=True,
            determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
            metrics={
                "threshold_db": threshold_db,
                "ratio": ratio,
                "attack_ms": attack_ms,
                "release_ms": release_ms,
                "makeup_db": makeup_db,
            },
        )


__all__ = [
    "MAX_ATTACK_MS",
    "MAX_MAKEUP_DB",
    "MAX_RATIO",
    "MAX_RELEASE_MS",
    "MAX_THRESHOLD_DB",
    "MIN_ATTACK_MS",
    "MIN_MAKEUP_DB",
    "MIN_RATIO",
    "MIN_RELEASE_MS",
    "MIN_THRESHOLD_DB",
    "DynamicsAdapter",
]
