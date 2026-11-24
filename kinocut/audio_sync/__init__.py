"""Stem-aware sound placement, sample-domain hit stacks, and mix audition."""

from .audition import build_ab_audition
from .masking import nudge_off_transients, place_events_with_stem
from .onsets import Onset, detect_onsets, pocket_lock
from .phase_stack import align_hit_stack, detect_sample_onset

__all__ = [
    "Onset",
    "align_hit_stack",
    "build_ab_audition",
    "detect_onsets",
    "detect_sample_onset",
    "nudge_off_transients",
    "place_events_with_stem",
    "pocket_lock",
]
