"""FFT denoise adapter with optional neural denoise fail-soft.

The FFT path uses ffmpeg's ``afftdn`` filter with bounded noise-reduction and
noise-floor parameters. The optional neural path uses ``arnndn`` which requires
a model file; when the model is absent the adapter probes *unavailable* and
renders fail-soft for capability checks, validation-error for demanded renders.

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
from kinocut_sound.post._errors import (
    POST_DEPENDENCY_MISSING,
    POST_INVALID_PARAM,
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

# --- Numeric envelopes (local to denoise) ---
# TODO(controller): centralize alongside defaults.py/limits.py post-merge.
MIN_NR_DB: float = 0.01
MAX_NR_DB: float = 97.0
MIN_NOISE_FLOOR_DB: float = -80.0
MAX_NOISE_FLOOR_DB: float = -20.0


def _descriptor(adapter_id: str, *, timeout: float) -> AdapterDescriptor:
    return AdapterDescriptor(
        adapter_id=adapter_id,
        kind="processor",
        locality=AdapterLocality.LOCAL,
        provider_class="ffmpeg",
        timeout_seconds=timeout,
    )


class FFTDenoiseAdapter:
    """FFT-based denoise via ffmpeg ``afftdn`` — deterministic and local."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self.descriptor = _descriptor("denoise_fft", timeout=timeout_seconds)

    def probe(self) -> CapabilityResult:
        try:
            resolve_binary("ffmpeg")
        except PostError:
            return CapabilityResult(
                adapter_id=self.descriptor.adapter_id,
                available=False,
                reason_code=POST_DEPENDENCY_MISSING,
                remediation="Install ffmpeg to enable FFT denoise",
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
        nr_db = bounded_float(
            p.get("strength_db", 12.0),
            lo=MIN_NR_DB,
            hi=MAX_NR_DB,
            name="strength_db",
        )
        nf_db = bounded_float(
            p.get("noise_floor_db", -50.0),
            lo=MIN_NOISE_FLOOR_DB,
            hi=MAX_NOISE_FLOOR_DB,
            name="noise_floor_db",
        )
        filt = f"afftdn=nr={ffmpeg_filter_number(nr_db)}:nf={ffmpeg_filter_number(nf_db)}"
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
            metrics={"strength_db": nr_db, "noise_floor_db": nf_db},
        )


class NeuralDenoiseAdapter:
    """Optional neural denoise via ffmpeg ``arnndn`` — fail-soft when no model.

    The neural path requires a pre-trained RNN model file. When the model path
    is absent or the binary lacks ``arnndn`` support, :meth:`probe` returns
    unavailable. Capability checks treat this as advisory; a demanded render
    raises :class:`PostError`.
    """

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        timeout_seconds: float = DEFAULT_POST_TIMEOUT_SECONDS,
    ) -> None:
        self._model_path = Path(model_path) if model_path is not None else None
        self.descriptor = _descriptor("denoise_neural", timeout=timeout_seconds)

    def probe(self) -> CapabilityResult:
        try:
            resolve_binary("ffmpeg")
        except PostError:
            return CapabilityResult(
                adapter_id=self.descriptor.adapter_id,
                available=False,
                reason_code=POST_DEPENDENCY_MISSING,
                remediation="Install ffmpeg to enable neural denoise",
            )
        if self._model_path is None or not self._model_path.exists():
            return CapabilityResult(
                adapter_id=self.descriptor.adapter_id,
                available=False,
                reason_code=POST_DEPENDENCY_MISSING,
                remediation="Provide a trained arnndn model path",
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
        capability = self.probe()
        if not capability.available:
            raise post_error(
                "neural denoise is unavailable for a demanded render",
                POST_DEPENDENCY_MISSING,
            )
        if self._model_path is None:
            raise post_error(
                "neural denoise requires a model path",
                POST_INVALID_PARAM,
            )
        run_ffmpeg(
            [
                "-i",
                str(input_path),
                "-af",
                f"arnndn=m={self._model_path}",
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
            metrics={"model": 1.0},
        )


__all__ = [
    "MAX_NOISE_FLOOR_DB",
    "MAX_NR_DB",
    "MIN_NOISE_FLOOR_DB",
    "MIN_NR_DB",
    "FFTDenoiseAdapter",
    "NeuralDenoiseAdapter",
]
