"""Batch processing planner with per-clip override policy.

Plans a batch of clips through the :class:`PostChain`, applying per-clip
stage-parameter overrides on top of a shared base plan. Each clip carries a
bounded id, an input path, an output path, and optional per-stage overrides.

Nothing in this module imports from ``kinocut.*`` runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from kinocut_sound._canonical import BoundedCode
from kinocut_sound.post._errors import (
    POST_CLIP_MISSING,
    POST_INVALID_PARAM,
    post_error,
)
from kinocut_sound.post.chain import (
    CANONICAL_STAGE_ORDER,
    PostChain,
    PostChainResult,
    PostContext,
)

# TODO(controller): centralize alongside defaults.py/limits.py post-merge.
MAX_BATCH_CLIPS: int = 512


@dataclass(frozen=True)
class BatchClip:
    """One clip in a batch: bounded id, input/output, per-stage overrides."""

    clip_id: str
    input_path: Path
    output_path: Path
    stage_overrides: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        BoundedCode(self.clip_id)
        if not Path(self.input_path).exists():
            raise post_error(
                f"clip input does not exist: {self.clip_id}",
                POST_CLIP_MISSING,
            )
        for stage_id in self.stage_overrides:
            if stage_id not in CANONICAL_STAGE_ORDER:
                raise post_error(
                    f"unknown stage override: {stage_id}",
                    POST_INVALID_PARAM,
                )


@dataclass(frozen=True)
class BatchResult:
    """The result of a batch run — one chain result per clip, in order."""

    results: tuple[tuple[str, PostChainResult], ...] = ()

    @property
    def clip_ids(self) -> tuple[str, ...]:
        return tuple(clip_id for clip_id, _ in self.results)

    def result_for(self, clip_id: str) -> PostChainResult:
        for cid, result in self.results:
            if cid == clip_id:
                return result
        raise post_error(f"no result for clip: {clip_id}", POST_CLIP_MISSING)


class BatchPlanner:
    """Plan and run a batch of clips through the post chain.

    The base ``stage_params`` are shared by all clips. Each clip's
    ``stage_overrides`` are merged on top of the base params per-stage (shallow
    merge at the stage level), so a clip can override individual parameters
    without restating the entire stage config.
    """

    def __init__(
        self,
        chain: PostChain,
        *,
        base_stage_params: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        self._chain = chain
        self._base = dict(base_stage_params or {})

    def run(
        self,
        clips: list[BatchClip] | tuple[BatchClip, ...],
        *,
        ctx: PostContext,
    ) -> BatchResult:
        if not isinstance(clips, (list, tuple)):
            raise post_error("clips must be a list or tuple", POST_INVALID_PARAM)
        if len(clips) > MAX_BATCH_CLIPS:
            raise post_error(
                f"batch exceeds ceiling of {MAX_BATCH_CLIPS} clips",
                POST_INVALID_PARAM,
            )
        results: list[tuple[str, PostChainResult]] = []
        for clip in clips:
            merged = self._merge_params(clip.stage_overrides)
            result = self._chain.run(
                clip.input_path,
                clip.output_path,
                ctx=ctx,
                stage_params=merged,
            )
            results.append((clip.clip_id, result))
        return BatchResult(results=tuple(results))

    def _merge_params(
        self,
        overrides: Mapping[str, Mapping[str, object]],
    ) -> dict[str, Mapping[str, object]]:
        merged: dict[str, Mapping[str, object]] = {}
        for stage_id in CANONICAL_STAGE_ORDER:
            base_stage = dict(self._base.get(stage_id, {}))
            override_stage = dict(overrides.get(stage_id, {}))
            combined = {**base_stage, **override_stage}
            if combined:
                merged[stage_id] = combined
        return merged


__all__ = [
    "MAX_BATCH_CLIPS",
    "BatchClip",
    "BatchPlanner",
    "BatchResult",
]
