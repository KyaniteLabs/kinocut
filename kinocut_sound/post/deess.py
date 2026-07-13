"""De-essing adapter — sibilant energy reduction.

Uses ffmpeg's ``deesser`` filter with bounded intensity, max de-essing, and
frequency parameters. The frequency parameter is normalised 0..1 as ffmpeg
expects; the adapter exposes it as a band centre in Hz for caller clarity and
converts internally.

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
MIN_INTENSITY: float = 0.0
MAX_INTENSITY: float = 1.0
MIN_MAX_DEESS: float = 0.0
MAX_MAX_DEESS: float = 1.0
MIN_FREQ_HZ: float = 2000.0
MAX_FREQ_HZ: float = 12000.0


class DeEssAdapter:
    """De-essing via ffmpeg ``deesser`` — reduces sibilant energy."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="deess",
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
                remediation="Install ffmpeg to enable de-essing",
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
        intensity = bounded_float(
            p.get("intensity", 0.5),
            lo=MIN_INTENSITY,
            hi=MAX_INTENSITY,
            name="intensity",
        )
        max_deess = bounded_float(
            p.get("max_deess", 0.5),
            lo=MIN_MAX_DEESS,
            hi=MAX_MAX_DEESS,
            name="max_deess",
        )
        freq_hz = bounded_float(
            p.get("frequency_hz", 7000.0),
            lo=MIN_FREQ_HZ,
            hi=MAX_FREQ_HZ,
            name="frequency_hz",
        )
        # Convert Hz to ffmpeg's normalised 0..1 frequency parameter.
        freq_norm = (freq_hz - MIN_FREQ_HZ) / (MAX_FREQ_HZ - MIN_FREQ_HZ)
        filt = (
            f"deesser=i={ffmpeg_filter_number(intensity, digits=4)}"
            f":m={ffmpeg_filter_number(max_deess, digits=4)}"
            f":f={ffmpeg_filter_number(freq_norm, digits=4)}"
            f":s=o"
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
                "intensity": intensity,
                "max_deess": max_deess,
                "frequency_hz": freq_hz,
            },
        )


__all__ = [
    "MAX_FREQ_HZ",
    "MAX_INTENSITY",
    "MAX_MAX_DEESS",
    "MIN_FREQ_HZ",
    "MIN_INTENSITY",
    "MIN_MAX_DEESS",
    "DeEssAdapter",
]
