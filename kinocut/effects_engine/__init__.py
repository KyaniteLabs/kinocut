"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

# Re-exports for backward compatibility
from .core import (
    effect_chromatic_aberration as effect_chromatic_aberration,
    effect_glow as effect_glow,
    effect_noise as effect_noise,
    effect_scanlines as effect_scanlines,
    effect_vignette as effect_vignette,
)
from .layout import layout_grid as layout_grid, layout_pip as layout_pip
from .mograph import mograph_count as mograph_count, mograph_progress as mograph_progress
from .text import text_animated as text_animated, text_subtitles as text_subtitles
from .utility import auto_chapters as auto_chapters, video_info_detailed as video_info_detailed
