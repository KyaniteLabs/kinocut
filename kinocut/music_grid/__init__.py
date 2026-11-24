"""Musical timeline placement, validation, and performance timing."""

from .grid import FINE_GRID_384, MusicalGrid, estimate_bpm_from_audio, round_half_up, validate_edit_points
from .groove import quantize_real_timestamps
from .keyframe_lint import lint_composition_keyframes, snap_duration_to_grid
from .microtiming import MicrotimingConfig, TimingCurve
from .rhythm_cells import place_rhythm_cell

__all__ = [
    "FINE_GRID_384",
    "MicrotimingConfig",
    "MusicalGrid",
    "TimingCurve",
    "estimate_bpm_from_audio",
    "lint_composition_keyframes",
    "place_rhythm_cell",
    "quantize_real_timestamps",
    "round_half_up",
    "snap_duration_to_grid",
    "validate_edit_points",
]
