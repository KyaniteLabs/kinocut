"""CLI handlers for visual effect commands."""

from __future__ import annotations

from typing import Any

from .common import _auto_output, _with_spinner
from .formatting import _format_path_panel
from .runner import CommandRunner, _out


def _register_basic_effects_commands(runner: CommandRunner) -> None:
    """Register vignette, glow, and noise effect commands."""

    def _vignette(a, j):
        from ..effects_engine import effect_vignette

        out = a.output or _auto_output(a.input, "vignette")
        r = _with_spinner(
            "Applying vignette...",
            effect_vignette,
            a.input,
            out,
            intensity=a.intensity,
            radius=a.radius,
            smoothness=a.smoothness,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Vignette applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("effect-vignette", _vignette)

    def _glow(a, j):
        from ..effects_engine import effect_glow

        out = a.output or _auto_output(a.input, "glow")
        r = _with_spinner(
            "Applying glow...", effect_glow, a.input, out, intensity=a.intensity, radius=a.radius, threshold=a.threshold
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Glow applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("effect-glow", _glow)

    def _noise(a, j):
        from ..effects_engine import effect_noise

        out = a.output or _auto_output(a.input, "noise")
        r = _with_spinner(
            "Applying noise...", effect_noise, a.input, out, intensity=a.intensity, mode=a.mode, animated=not a.static
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Noise applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("effect-noise", _noise)


def _register_advanced_effects_commands(runner: CommandRunner) -> None:
    """Register scanlines and chromatic aberration effect commands."""

    def _scanlines(a, j):
        from ..effects_engine import effect_scanlines

        out = a.output or _auto_output(a.input, "scanlines")
        r = _with_spinner(
            "Applying scanlines...",
            effect_scanlines,
            a.input,
            out,
            line_height=a.line_height,
            opacity=a.opacity,
            flicker=a.flicker,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Scanlines applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("effect-scanlines", _scanlines)

    def _chromatic(a, j):
        from ..effects_engine import effect_chromatic_aberration

        out = a.output or _auto_output(a.input, "chromatic")
        r = _with_spinner(
            "Applying chromatic aberration...",
            effect_chromatic_aberration,
            a.input,
            out,
            intensity=a.intensity,
            angle=a.angle,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Chromatic aberration applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("effect-chromatic-aberration", _chromatic)


def handle_effect_command(args: Any, *, use_json: bool) -> bool:
    """Handle visual effect commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)
    _register_basic_effects_commands(runner)
    _register_advanced_effects_commands(runner)
    return runner.dispatch()
