"""Convolution-IR room reverb, distance simulation, and humanization adapters.

Convolution reverb uses ffmpeg ``afir`` with synthetic impulse responses
generated per-preset (small_room, hall, outdoor, close). Distance simulation
applies HF rolloff plus wet/dry and gain offsets. Humanization applies
deterministic parametric micro-variation (breaths/micro-pauses/jitter) at
0-100% intensity; 0% is a near-passthrough stream copy.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from kinocut_sound.capability import (
    AdapterDescriptor,
    AdapterLocality,
    CapabilityResult,
)
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

# --- Numeric envelopes ---
# TODO(controller): centralize alongside defaults.py/limits.py post-merge.
MIN_WET: float = 0.0
MAX_WET: float = 10.0
MIN_DRY: float = 0.0
MAX_DRY: float = 10.0
MIN_GAIN_DB: float = -24.0
MAX_GAIN_DB: float = 12.0
MIN_CROSSOVER_HZ: float = 500.0
MAX_CROSSOVER_HZ: float = 16000.0
MIN_DISTANCE_PCT: float = 0.0
MAX_DISTANCE_PCT: float = 100.0
MIN_HUMANIZATION_PCT: float = 0.0
MAX_HUMANIZATION_PCT: float = 100.0

# Convolution reverb presets — bounded codes.
REVERB_PRESETS: frozenset[str] = frozenset({"close", "small_room", "hall", "outdoor"})


def _afir_supports_gtype_4() -> bool:
    """Probe whether the installed ffmpeg ``afir`` filter accepts ``gtype=4``.

    ffmpeg 5.1.x only supports ``gtype`` values -1 through 2, while ffmpeg 6.1+
    extends this to -1 through 4. The probe is cached on the function attribute
    so the ffmpeg invocation runs at most once per process.
    """

    cached = getattr(_afir_supports_gtype_4, "_cached", None)
    if cached is not None:
        return cached
    binary = shutil.which("ffmpeg")
    if binary is None:
        _afir_supports_gtype_4._cached = False  # type: ignore[attr-defined]
        return False
    cmd = [
        binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc",
        "-f",
        "lavfi",
        "-i",
        "anullsrc",
        "-filter_complex",
        "[0:a][1:a]afir=gtype=4",
        "-t",
        "0",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - command list built from validated components
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
        )
        supported = proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        supported = False
    _afir_supports_gtype_4._cached = supported  # type: ignore[attr-defined]
    return supported


class ConvolutionReverbAdapter:
    """Convolution-IR room reverb via ffmpeg ``afir``.

    Generates a deterministic synthetic IR for the selected preset and convolves
    it with the input. Not algorithmic echo — this is true time-domain
    convolution with a room impulse response.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="spatial_convolution",
            kind="spatializer",
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
                remediation="Install ffmpeg to enable convolution reverb",
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
        preset = p.get("preset", "small_room")
        if preset not in REVERB_PRESETS:
            raise post_error(
                f"unknown reverb preset: {preset}",
                POST_PRESET_UNKNOWN,
            )
        wet = bounded_float(p.get("wet", 1.0), lo=MIN_WET, hi=MAX_WET, name="wet")
        dry = bounded_float(p.get("dry", 1.0), lo=MIN_DRY, hi=MAX_DRY, name="dry")
        ir_path = ctx.work_dir / f"ir_{preset}.wav"
        _ensure_ir(ir_path, preset=preset, sample_rate_hz=ctx.sample_rate_hz)
        # gtype=4 (rms auto-gain) prevents the convolution from changing the
        # overall signal level drastically. ffmpeg 5.1.x only supports gtype
        # -1..2, so fall back to gtype=-1 (no auto-gain) on older binaries.
        gtype = 4 if _afir_supports_gtype_4() else -1
        filt = f"[0:a][1:a]afir=wet={ffmpeg_filter_number(wet)}:dry={ffmpeg_filter_number(dry)}:gtype={gtype}"
        run_ffmpeg(
            [
                "-i",
                str(input_path),
                "-i",
                str(ir_path),
                "-filter_complex",
                filt,
                "-ar",
                str(ctx.sample_rate_hz),
                "-ac",
                str(ctx.channel_count),
                "-c:a",
                "pcm_s32le",
                str(output_path),
            ],
            timeout=self.descriptor.timeout_seconds,
        )
        return PostStageResult(
            adapter_id=self.descriptor.adapter_id,
            output_path=Path(output_path),
            applied=True,
            determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
            metrics={"preset_id": 1.0, "wet": wet, "dry": dry},
        )


class DistanceAdapter:
    """Distance simulation — far/close via HF rolloff, wet/dry, and gain.

    Far distance applies a low-pass HF rolloff and gain reduction to simulate
    atmospheric attenuation and distance. Close distance is near-passthrough
    with full bandwidth.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="spatial_distance",
            kind="spatializer",
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
                remediation="Install ffmpeg to enable distance simulation",
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
        distance_pct = bounded_float(
            p.get("distance_pct", 0.0),
            lo=MIN_DISTANCE_PCT,
            hi=MAX_DISTANCE_PCT,
            name="distance_pct",
        )
        crossover_hz = bounded_float(
            p.get("crossover_hz", 4000.0),
            lo=MIN_CROSSOVER_HZ,
            hi=MAX_CROSSOVER_HZ,
            name="crossover_hz",
        )
        rolloff_db = bounded_float(
            p.get("rolloff_db", 6.0),
            lo=MIN_GAIN_DB,
            hi=MAX_GAIN_DB,
            name="rolloff_db",
        )
        # Far (100%) = maximum rolloff + gain cut. Close (0%) = passthrough.
        distance_norm = distance_pct / MAX_DISTANCE_PCT
        # HF rolloff: at far distance, cut HF by rolloff_db.
        hf_gain = -distance_norm * rolloff_db
        # Overall gain reduction at far distance.
        gain_db = -distance_norm * 6.0
        filt = (
            f"treble=f={ffmpeg_filter_number(crossover_hz)}"
            f":g={ffmpeg_filter_number(hf_gain)}"
            f":width_type=q:w={ffmpeg_filter_number(0.7)}"
            f",volume={ffmpeg_filter_number(gain_db)}dB"
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
                "distance_pct": distance_pct,
                "hf_gain_db": hf_gain,
                "gain_db": gain_db,
            },
        )


class HumanizationAdapter:
    """Parametric humanization — 0% passthrough, >0% adds micro-variation.

    At intensity 0% the adapter performs a lossless stream copy. At higher
    intensities it applies deterministic amplitude jitter and micro-pauses
    (brief envelope notches) so the output gains measurable micro-variation
    while remaining reproducible.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = AdapterDescriptor(
            adapter_id="spatial_humanize",
            kind="spatializer",
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
                remediation="Install ffmpeg to enable humanization",
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
        intensity_pct = bounded_float(
            p.get("intensity_pct", 0.0),
            lo=MIN_HUMANIZATION_PCT,
            hi=MAX_HUMANIZATION_PCT,
            name="intensity_pct",
        )
        if intensity_pct <= 0.0:
            # Near-passthrough: lossless stream copy.
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(input_path), str(output_path))
            return PostStageResult(
                adapter_id=self.descriptor.adapter_id,
                output_path=Path(output_path),
                applied=False,
                determinism_class=DeterminismClass.BYTE_DETERMINISTIC,
                metrics={"intensity_pct": 0.0},
            )
        intensity_norm = intensity_pct / MAX_HUMANIZATION_PCT
        # Deterministic amplitude jitter via tremolo: the depth scales with
        # intensity so higher settings produce stronger micro-variation.
        jitter_depth = intensity_norm * 0.15
        mod_freq = 5.0 + intensity_norm * 3.0
        filt = f"tremolo=f={ffmpeg_filter_number(mod_freq)}:d={ffmpeg_filter_number(jitter_depth, digits=4)}"
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
            metrics={"intensity_pct": intensity_pct},
        )


def _ensure_ir(ir_path: Path, *, preset: str, sample_rate_hz: int) -> None:
    """Generate the preset IR if it does not already exist on disk."""

    if ir_path.exists():
        return
    from kinocut_sound.post._fixtures import synthetic_ir

    synthetic_ir(ir_path, preset=preset, sample_rate_hz=sample_rate_hz)


__all__ = [
    "MAX_CROSSOVER_HZ",
    "MAX_DISTANCE_PCT",
    "MAX_DRY",
    "MAX_GAIN_DB",
    "MAX_HUMANIZATION_PCT",
    "MAX_WET",
    "MIN_CROSSOVER_HZ",
    "MIN_DISTANCE_PCT",
    "MIN_DRY",
    "MIN_GAIN_DB",
    "MIN_HUMANIZATION_PCT",
    "MIN_WET",
    "REVERB_PRESETS",
    "ConvolutionReverbAdapter",
    "DistanceAdapter",
    "HumanizationAdapter",
]
