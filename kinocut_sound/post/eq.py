"""5-band parametric EQ adapter with named per-character/line presets.

Uses five chained ffmpeg ``equalizer`` filters covering low shelf, low-mid,
mid (presence), high-mid, and high shelf bands. Named presets are bounded codes
so a host path or prose cannot ride in.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
from kinocut_sound.post._errors import (
    POST_DEPENDENCY_MISSING,
    POST_INVALID_PARAM,
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

# --- Numeric envelopes ---
# TODO(controller): centralize alongside defaults.py/limits.py post-merge.
MIN_GAIN_DB: float = -24.0
MAX_GAIN_DB: float = 24.0
MIN_Q: float = 0.1
MAX_Q: float = 6.0

# Canonical 5-band centre frequencies (Hz).
BAND_FREQUENCIES: tuple[float, ...] = (120.0, 500.0, 2500.0, 6000.0, 12000.0)
DEFAULT_Q: float = 1.0


@dataclass(frozen=True)
class EqBandGains:
    """Five dB gains for the canonical bands — order: low, low-mid, mid, hi-mid, high."""

    low: float = 0.0
    low_mid: float = 0.0
    mid: float = 0.0
    high_mid: float = 0.0
    high: float = 0.0

    def as_tuple(self) -> tuple[float, ...]:
        return (self.low, self.low_mid, self.mid, self.high_mid, self.high)


# Named per-character/line presets. Each maps to five dB gains.
# These are the static, code-owned preset library — not user-extensible.
EQ_PRESETS: dict[str, EqBandGains] = {
    "neutral": EqBandGains(0.0, 0.0, 0.0, 0.0, 0.0),
    "warm": EqBandGains(3.0, 2.0, 0.0, -1.5, -2.0),
    "bright": EqBandGains(-1.5, 0.0, 1.5, 3.0, 4.0),
    "intimate": EqBandGains(4.0, 2.0, 0.0, -1.0, -3.0),
    "authoritative": EqBandGains(-2.0, -1.0, 3.0, 2.0, 0.0),
    "narrator": EqBandGains(0.0, 0.0, 2.0, 1.0, 0.0),
    "confessional": EqBandGains(2.0, 1.0, 0.0, 2.0, 3.0),
}

PRESET_NAMES: frozenset[str] = frozenset(EQ_PRESETS)


class EqAdapter:
    """5-band parametric EQ via five chained ffmpeg ``equalizer`` filters."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="eq_5band",
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
                remediation="Install ffmpeg to enable parametric EQ",
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
        preset_name = p.get("preset", "neutral")
        if preset_name not in EQ_PRESETS:
            raise post_error(
                f"unknown EQ preset: {preset_name}",
                POST_PRESET_UNKNOWN,
            )
        preset = EQ_PRESETS[preset_name]
        # Allow per-band override via explicit gains parameter.
        override = p.get("gains")
        gains = _validate_gains(override) if override is not None else preset.as_tuple()
        q = bounded_float(p.get("q", DEFAULT_Q), lo=MIN_Q, hi=MAX_Q, name="q")
        filt = ",".join(
            f"equalizer=f={ffmpeg_filter_number(freq)}:t=q:w={ffmpeg_filter_number(q)}:g={ffmpeg_filter_number(gain)}"
            for freq, gain in zip(BAND_FREQUENCIES, gains, strict=True)
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
                "preset_id": 1.0,
                "gains_low": gains[0],
                "gains_mid": gains[2],
                "gains_high": gains[4],
            },
        )


def _validate_gains(value: object) -> tuple[float, ...]:
    """Validate a 5-element gain tuple, returning bounded floats."""

    if not isinstance(value, (tuple, list)) or len(value) != 5:
        raise post_error("gains must be a 5-element sequence", POST_INVALID_PARAM)
    return tuple(bounded_float(g, lo=MIN_GAIN_DB, hi=MAX_GAIN_DB, name=f"gains[{i}]") for i, g in enumerate(value))


__all__ = [
    "BAND_FREQUENCIES",
    "DEFAULT_Q",
    "EQ_PRESETS",
    "MAX_GAIN_DB",
    "MAX_Q",
    "MIN_GAIN_DB",
    "MIN_Q",
    "PRESET_NAMES",
    "EqAdapter",
    "EqBandGains",
]
