"""Kinocut Python client effects operations."""

from __future__ import annotations

import warnings

from ..errors import MCPVideoError
from ..models import EditResult
from ..validation import (
    VALID_GRID_LAYOUTS,
    VALID_MOGRAPH_STYLES,
    VALID_PIP_POSITIONS,
    VALID_TEXT_ANIMATIONS,
    VALID_TEXT_POSITIONS,
)


class ClientEffectsMixin:
    """Effects operations mixin."""

    def effect_vignette(
        self,
        video: str,
        output: str,
        intensity: float = 0.5,
        radius: float = 0.8,
        smoothness: float = 0.5,
    ) -> EditResult:
        """Apply vignette effect - darkened edges."""
        from ..effects_engine import effect_vignette

        return effect_vignette(
            input_path=video, output=output, intensity=intensity, radius=radius, smoothness=smoothness
        )

    def effect_chromatic_aberration(
        self,
        video: str,
        output: str,
        intensity: float = 2.0,
        angle: float = 0,
    ) -> EditResult:
        """Apply RGB channel separation effect."""
        from ..effects_engine import effect_chromatic_aberration

        return effect_chromatic_aberration(input_path=video, output=output, intensity=intensity, angle=angle)

    def effect_scanlines(
        self,
        video: str | None = None,
        output: str | None = None,
        line_height: int = 2,
        opacity: float = 0.3,
        flicker: float = 0.1,
        *,
        input_path: str | None = None,
        output_path: str | None = None,
        intensity: float | None = None,
    ) -> EditResult:
        """Apply CRT-style scanline overlay."""
        if intensity is not None:
            warnings.warn(
                "effect_scanlines(intensity=...) is accepted as an alias; use opacity=... for scanlines.",
                DeprecationWarning,
                stacklevel=2,
            )
            opacity = intensity
        from ..effects_engine import effect_scanlines

        return effect_scanlines(
            input_path=input_path,
            output=output_path,
            line_height=line_height,
            opacity=opacity,
            flicker=flicker,
        )

    def effect_noise(
        self,
        video: str,
        output: str,
        intensity: float = 0.05,
        mode: str = "film",
        animated: bool = True,
    ) -> EditResult:
        """Apply film grain / digital noise."""
        from ..effects_engine import effect_noise

        return effect_noise(input_path=video, output=output, intensity=intensity, mode=mode, animated=animated)

    def effect_glow(
        self,
        video: str | None = None,
        output: str | None = None,
        intensity: float = 0.5,
        radius: int = 10,
        threshold: float = 0.7,
        *,
        input_path: str | None = None,
        output_path: str | None = None,
    ) -> EditResult:
        """Apply bloom/glow effect for highlights."""
        from ..effects_engine import effect_glow

        return effect_glow(
            input_path=input_path, output=output_path, intensity=intensity, radius=radius, threshold=threshold
        )

    # ------------------------------------------------------------------
    # Layout & Composition
    # ------------------------------------------------------------------

    def layout_grid(
        self,
        clips: list[str],
        layout: str,
        output: str,
        gap: int = 10,
        padding: int = 20,
        background: str = "#141414",
    ) -> EditResult:
        """Create grid-based multi-video layout.

        Args:
            clips: List of video file paths
            layout: Grid layout (2x2, 3x1, 1x3, 2x3). CLI: -l/--layout
            output: Output video path
            gap: Pixels between clips
            padding: Padding around grid
            background: Background color hex

        Raises:
            ValueError: If layout is invalid
        """
        self._validate_choice("layout", layout, VALID_GRID_LAYOUTS)
        from ..effects_engine import layout_grid

        return layout_grid(clips, layout, output, gap, padding, background)

    def layout_pip(
        self,
        main: str,
        pip: str,
        output: str,
        position: str = "bottom-right",
        size: float = 0.25,
        margin: int = 20,
        rounded_corners: bool = True,
        border: bool = True,
        border_color: str = "#CCFF00",
        border_width: int = 2,
    ) -> EditResult:
        """Picture-in-picture overlay.

        Args:
            main: Main video path
            pip: Picture-in-picture video path
            output: Output video path
            position: Position (top-left, top-right, bottom-left, bottom-right). CLI: -p/--position
            size: PIP size as fraction of main (0-1)
            margin: Margin from edges in pixels
            rounded_corners: Apply rounded corners to PIP
            border: Add border around PIP
            border_color: Border color hex
            border_width: Border width in pixels

        Raises:
            ValueError: If position is invalid
        """
        self._validate_choice("position", position, VALID_PIP_POSITIONS)
        from ..effects_engine import layout_pip

        return layout_pip(
            main, pip, output, position, size, margin, rounded_corners, border, border_color, border_width
        )

    # ------------------------------------------------------------------
    # Text & Typography
    # ------------------------------------------------------------------

    def text_animated(
        self,
        video: str,
        text: str,
        output: str,
        animation: str = "fade",
        font: str = "Arial",
        size: int = 48,
        color: str = "white",
        position: str = "center",
        start: float = 0,
        duration: float = 3.0,
        typewriter_speed: float = 0.08,
    ) -> EditResult:
        """Add animated text to video."""
        if not text or not text.strip():
            raise MCPVideoError("Text cannot be empty", error_type="validation_error", code="invalid_parameter")
        self._validate_choice("animation", animation, VALID_TEXT_ANIMATIONS)
        self._validate_choice("position", position, VALID_TEXT_POSITIONS)
        from ..effects_engine import text_animated

        return text_animated(
            video, text, output, animation, font, size, color, position, start, duration, typewriter_speed
        )

    def text_subtitles(
        self,
        video: str,
        subtitles: str,
        output: str,
        style: dict | None = None,
    ) -> EditResult:
        """Burn subtitles from SRT/VTT with styling."""
        from ..effects_engine import text_subtitles

        return text_subtitles(video=video, subtitles=subtitles, output=output, style=style)

    def subtitles_styled(
        self,
        video: str,
        subtitles: str,
        output: str,
        style: dict | None = None,
    ) -> EditResult:
        """Burn subtitles from SRT/VTT with styling (alias for text_subtitles)."""
        return self.text_subtitles(video, subtitles, output, style)

    # ------------------------------------------------------------------
    # Motion Graphics
    # ------------------------------------------------------------------

    def mograph_count(
        self,
        start: int,
        end: int,
        duration: float,
        output: str,
        style: dict | None = None,
        fps: int = 30,
    ) -> EditResult:
        """Generate animated number counter video.

        Args:
            start: Starting number (CLI: positional arg)
            end: Ending number (CLI: positional arg)
            duration: Animation duration in seconds
            output: Output video path
            style: Style dict with optional keys: font, size, color, glow
            fps: Frame rate

        Note:
            In the CLI (video-mograph-count), start and end are positional arguments.
            In the Python client, they must be passed as named arguments.
        """
        if duration <= 0:
            raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")
        if fps <= 0:
            raise MCPVideoError("fps must be positive", error_type="validation_error", code="invalid_parameter")
        from ..effects_engine import mograph_count

        return mograph_count(start, end, duration, output, style, fps)

    def mograph_progress(
        self,
        duration: float,
        output: str,
        style: str = "bar",
        color: str = "#CCFF00",
        track_color: str = "#333333",
        fps: int = 30,
    ) -> EditResult:
        """Generate progress bar / loading animation."""
        if duration <= 0:
            raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")
        if fps <= 0:
            raise MCPVideoError("fps must be positive", error_type="validation_error", code="invalid_parameter")
        self._validate_choice("style", style, VALID_MOGRAPH_STYLES)
        from ..effects_engine import mograph_progress

        return mograph_progress(duration, output, style, color, track_color, fps)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def video_info_detailed(self, video: str) -> dict:
        """Get extended video metadata."""
        from ..effects_engine import video_info_detailed

        return video_info_detailed(video)

    def auto_chapters(self, video: str, threshold: float = 0.3) -> list[tuple[float, str]]:
        """Auto-detect scene changes and create chapters."""
        from ..effects_engine import auto_chapters

        return auto_chapters(video, threshold)

    # ------------------------------------------------------------------
    # Transitions (Wave 2)
    # ------------------------------------------------------------------

    def transition_glitch(
        self, clip1: str, clip2: str, output: str, duration: float = 0.5, intensity: float = 0.3
    ) -> EditResult:
        """Apply glitch transition between two video clips.

        Args:
            clip1: First video clip path
            clip2: Second video clip path
            output: Output video path
            duration: Transition duration in seconds. CLI: -d/--duration
            intensity: Glitch intensity 0-1. CLI: -i/--intensity
        """
        from ..transitions_engine import transition_glitch

        return transition_glitch(clip1, clip2, output, duration, intensity)

    def transition_pixelate(
        self, clip1: str, clip2: str, output: str, duration: float = 0.4, pixel_size: int = 50
    ) -> EditResult:
        """Apply pixelate transition between two video clips.

        Args:
            clip1: First video clip path
            clip2: Second video clip path
            output: Output video path
            duration: Transition duration in seconds. CLI: -d/--duration
            pixel_size: Maximum pixel size during transition. CLI: -p/--pixel-size
        """
        from ..transitions_engine import transition_pixelate

        return transition_pixelate(clip1, clip2, output, duration, pixel_size)

    def transition_morph(
        self, clip1: str, clip2: str, output: str, duration: float = 0.6, mesh_size: int = 10
    ) -> EditResult:
        """Apply morph transition between two video clips.

        Args:
            clip1: First video clip path
            clip2: Second video clip path
            output: Output video path
            duration: Transition duration in seconds. CLI: -d/--duration
            mesh_size: Grid subdivisions. CLI: -m/--mesh-size
        """
        from ..transitions_engine import transition_morph

        return transition_morph(clip1, clip2, output, duration, mesh_size)

    # ------------------------------------------------------------------
    # AI Features (Wave 3)
    # ------------------------------------------------------------------
