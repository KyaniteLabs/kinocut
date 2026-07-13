"""Fixed signal-order post-processing chain builder.

The chain enforces the canonical restoration/spatial order:

    denoise → de-ess → EQ → dynamics → convolution space
           → distance → humanization → loudness/true-peak

Each stage is a typed :class:`ProcessorAdapter` or :class:`SpatializerAdapter`
conforming to the :class:`kinocut_sound.registry.Adapter` protocol. Stages are
composed by piping each adapter's output WAV into the next adapter's input.

Nothing in this module imports from ``kinocut.*`` runtime. Adapter classes are
imported lazily inside :meth:`PostChain.build_default` so that the type/protocol
surface stays import-cycle-free.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from kinocut_sound.capability import AdapterDescriptor, CapabilityResult
from kinocut_sound.render_fingerprint import DeterminismClass


@dataclass(frozen=True)
class PostStageResult:
    """The result of one post-processing stage."""

    adapter_id: str
    output_path: Path
    applied: bool
    determinism_class: DeterminismClass
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PostChainResult:
    """The result of the entire chain — the final output plus per-stage trail."""

    output_path: Path
    stages: tuple[PostStageResult, ...]
    digest: str


@dataclass(frozen=True)
class PostContext:
    """Format and working-directory context shared by all chain stages."""

    work_dir: Path
    sample_rate_hz: int = 44100
    channel_count: int = 1


@runtime_checkable
class ProcessorAdapter(Protocol):
    """Typed processor adapter: transforms one WAV into another."""

    descriptor: AdapterDescriptor

    def probe(self) -> CapabilityResult: ...

    def process(
        self,
        input_path: Path,
        output_path: Path,
        *,
        ctx: PostContext,
        params: Mapping[str, object] | None = None,
    ) -> PostStageResult: ...


@runtime_checkable
class SpatializerAdapter(Protocol):
    """Typed spatializer adapter: applies room/distance/humanization."""

    descriptor: AdapterDescriptor

    def probe(self) -> CapabilityResult: ...

    def process(
        self,
        input_path: Path,
        output_path: Path,
        *,
        ctx: PostContext,
        params: Mapping[str, object] | None = None,
    ) -> PostStageResult: ...


# Canonical stage order — never reordered at runtime.
CANONICAL_STAGE_ORDER: tuple[str, ...] = (
    "denoise",
    "deess",
    "eq",
    "dynamics",
    "spatial",
    "distance",
    "humanize",
    "loudness",
)


class PostChain:
    """Compose fixed-order post-processing stages.

    Each entry in ``stages`` is a ``(stage_id, adapter)`` pair. The chain runs
    them in :data:`CANONICAL_STAGE_ORDER`, skipping any stage not present. A
    stage with ``params=None`` or empty params is still applied (the adapter's
    defaults take effect). Use ``skip_stages`` to bypass a stage entirely.
    """

    def __init__(
        self,
        stages: Mapping[str, ProcessorAdapter | SpatializerAdapter],
    ) -> None:
        unknown = set(stages) - set(CANONICAL_STAGE_ORDER)
        if unknown:
            raise ValueError(f"unknown stage ids: {sorted(unknown)}")
        self._stages = dict(stages)

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(sid for sid in CANONICAL_STAGE_ORDER if sid in self._stages)

    def run(
        self,
        input_path: Path,
        output_path: Path,
        *,
        ctx: PostContext,
        stage_params: Mapping[str, Mapping[str, object]] | None = None,
        skip_stages: frozenset[str] = frozenset(),
    ) -> PostChainResult:
        """Run the chain; write the final output and return the stage trail."""

        from kinocut_sound.post._fixtures import sha256_of_file

        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        stage_params = stage_params or {}
        current_input = Path(input_path)
        results: list[PostStageResult] = []
        for stage_id in CANONICAL_STAGE_ORDER:
            if stage_id not in self._stages or stage_id in skip_stages:
                continue
            adapter = self._stages[stage_id]
            stage_output = ctx.work_dir / f"stage_{stage_id}.wav"
            params = stage_params.get(stage_id)
            result = adapter.process(
                current_input,
                stage_output,
                ctx=ctx,
                params=params,
            )
            results.append(result)
            current_input = result.output_path
        # Copy the final stage output to the requested output_path.
        final_output = Path(output_path)
        final_output.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(current_input, final_output)
        digest = sha256_of_file(final_output)
        return PostChainResult(output_path=final_output, stages=tuple(results), digest=digest)

    @classmethod
    def build_default(cls, *, timeout_seconds: float = 30.0) -> PostChain:
        """Build the canonical chain with every stage wired to its adapter."""

        from kinocut_sound.post.deess import DeEssAdapter
        from kinocut_sound.post.denoise import FFTDenoiseAdapter
        from kinocut_sound.post.dynamics import DynamicsAdapter
        from kinocut_sound.post.eq import EqAdapter
        from kinocut_sound.post.loudness import LoudnessAdapter
        from kinocut_sound.post.spatial import (
            ConvolutionReverbAdapter,
            DistanceAdapter,
            HumanizationAdapter,
        )

        stages: dict[str, ProcessorAdapter | SpatializerAdapter] = {
            "denoise": FFTDenoiseAdapter(timeout_seconds=timeout_seconds),
            "deess": DeEssAdapter(timeout_seconds=timeout_seconds),
            "eq": EqAdapter(timeout_seconds=timeout_seconds),
            "dynamics": DynamicsAdapter(timeout_seconds=timeout_seconds),
            "spatial": ConvolutionReverbAdapter(timeout_seconds=timeout_seconds),
            "distance": DistanceAdapter(timeout_seconds=timeout_seconds),
            "humanize": HumanizationAdapter(timeout_seconds=timeout_seconds),
            "loudness": LoudnessAdapter(timeout_seconds=timeout_seconds),
        }
        return cls(stages)


def _copy_file(src: Path, dst: Path) -> None:
    """Copy a file, creating parent directories."""

    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src), str(dst))


__all__ = [
    "CANONICAL_STAGE_ORDER",
    "PostChain",
    "PostChainResult",
    "PostContext",
    "PostStageResult",
    "ProcessorAdapter",
    "SpatializerAdapter",
]
