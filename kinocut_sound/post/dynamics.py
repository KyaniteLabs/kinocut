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

# --- Numeric envelopes ---
# TODO(controller): centralize alongside defaults.py/limits.py post-merge.
MIN_THRESHOLD_DB: float = -60.0
MAX_THRESHOLD_DB: float = 0.0
MIN_RATIO: float = 1.0
MAX_RATIO: float = 20.0
MIN_ATTACK_MS: float = 0.01
MAX_ATTACK_MS: float = 2000.0
MIN_RELEASE_MS: float = 0.01
MAX_RELEASE_MS: float = 9000.0
MIN_MAKEUP_DB: float = 0.0
MAX_MAKEUP_DB: float = 24.0


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
