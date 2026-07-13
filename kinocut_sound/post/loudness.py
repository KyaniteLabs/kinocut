"""Loudness normalization and true-peak limiting adapter.

Uses ffmpeg ``loudnorm`` (EBU R128) followed by ``alimiter`` for true-peak
ceiling enforcement. Named preset targets come from the existing
:class:`kinocut_sound.delivery.DeliveryPreset` and :class:`LoudnessTarget`
contracts so the post chain's numeric targets stay aligned with the delivery
policy surface.

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
from kinocut_sound.delivery import DeliveryPreset, LoudnessTarget
from kinocut_sound.post._errors import (
    POST_DEPENDENCY_MISSING,
    POST_PRESET_UNKNOWN,
    PostError,
    post_error,
)
from kinocut_sound.post._subprocess import (
    DEFAULT_POST_TIMEOUT_SECONDS,
    bounded_float,
    ffmpeg_filter_number,
    resolve_binary,
    run_ffmpeg,
)
from kinocut_sound.post.chain import PostContext, PostStageResult
from kinocut_sound.render_fingerprint import DeterminismClass

# Reuse the canonical delivery preset names as loudness target presets.
LOUDNESS_PRESET_NAMES: frozenset[str] = frozenset({preset.value for preset in DeliveryPreset})


class LoudnessAdapter:
    """Loudness normalization + true-peak limiter via ffmpeg.

    Accepts a named preset (``stream_-14``, ``podcast_-16``,
    ``broadcast_ebu_r128_-23``, ``broadcast_atsc_a85_-24``) or explicit
    ``integrated_lufs`` / ``true_peak_dbtp`` overrides. Always runs
    ``loudnorm`` for loudness and ``alimiter`` for true-peak ceiling.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="loudness_normalize",
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
                remediation="Install ffmpeg to enable loudness normalization",
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
        target = self._resolve_target(p)
        # loudnorm expects a negative true-peak ceiling below 0.
        tp_ceiling = min(target.true_peak_dbtp, -0.1)
        limit_linear = 10.0 ** (tp_ceiling / 20.0)
        filt = (
            f"loudnorm="
            f"I={ffmpeg_filter_number(target.integrated_lufs)}"
            f":TP={ffmpeg_filter_number(tp_ceiling)}"
            f":LRA={ffmpeg_filter_number(11.0)}"
            f":linear=true"
            f",alimiter="
            f"limit={ffmpeg_filter_number(limit_linear, digits=6)}"
            f":attack={ffmpeg_filter_number(5.0)}"
            f":release={ffmpeg_filter_number(50.0)}"
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
            determinism_class=DeterminismClass.SIGNAL_EQUIVALENT,
            metrics={
                "target_integrated_lufs": target.integrated_lufs,
                "target_true_peak_dbtp": target.true_peak_dbtp,
                "tolerance_lu": target.tolerance_lu,
            },
        )

    @staticmethod
    def _resolve_target(params: Mapping[str, object]) -> LoudnessTarget:
        """Resolve the loudness target from a named preset or explicit overrides."""

        preset_value = params.get("preset")
        if preset_value is not None:
            if not isinstance(preset_value, str) or preset_value not in LOUDNESS_PRESET_NAMES:
                raise post_error(
                    f"unknown loudness preset: {preset_value}",
                    POST_PRESET_UNKNOWN,
                )
            return LoudnessTarget.for_preset(DeliveryPreset(preset_value))
        # Explicit overrides.
        integrated_lufs = bounded_float(
            params.get("integrated_lufs", -14.0),
            lo=-70.0,
            hi=-5.0,
            name="integrated_lufs",
        )
        true_peak_dbtp = bounded_float(
            params.get("true_peak_dbtp", -1.0),
            lo=-9.0,
            hi=-0.1,
            name="true_peak_dbtp",
        )
        tolerance_lu = bounded_float(
            params.get("tolerance_lu", 1.0),
            lo=0.1,
            hi=2.0,
            name="tolerance_lu",
        )
        return LoudnessTarget(
            integrated_lufs=integrated_lufs,
            true_peak_dbtp=true_peak_dbtp,
            tolerance_lu=tolerance_lu,
        )


__all__ = [
    "LOUDNESS_PRESET_NAMES",
    "LoudnessAdapter",
]
