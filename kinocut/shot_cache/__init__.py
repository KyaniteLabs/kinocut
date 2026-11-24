"""Render independent video shots and splice their cached streams in plan order."""

from .cache import ShotSpec, compute_shot_digest, render_shot_plan
from .concat import splice_shots_lossless, verify_concat_compatibility

__all__ = [
    "ShotSpec",
    "compute_shot_digest",
    "render_shot_plan",
    "splice_shots_lossless",
    "verify_concat_compatibility",
]
