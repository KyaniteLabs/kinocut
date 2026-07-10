"""CLI handlers for transition commands."""

from __future__ import annotations

from typing import Any

from .common import _with_spinner
from .formatting import _format_path_panel
from .runner import CommandRunner, _out


def handle_transition_command(args: Any, *, use_json: bool) -> bool:
    """Handle transition commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _glitch(a, j):
        from ..transitions_engine import transition_glitch

        r = _with_spinner(
            "Applying glitch transition...",
            transition_glitch,
            a.clip1,
            a.clip2,
            a.output,
            duration=a.duration,
            intensity=a.intensity,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Glitch transition", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("transition-glitch", _glitch)

    def _morph(a, j):
        from ..transitions_engine import transition_morph

        r = _with_spinner(
            "Applying morph transition...",
            transition_morph,
            a.clip1,
            a.clip2,
            a.output,
            duration=a.duration,
            mesh_size=a.mesh_size,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Morph transition", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("transition-morph", _morph)

    def _pixelate(a, j):
        from ..transitions_engine import transition_pixelate

        r = _with_spinner(
            "Applying pixelate transition...",
            transition_pixelate,
            a.clip1,
            a.clip2,
            a.output,
            duration=a.duration,
            pixel_size=a.pixel_size,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Pixelate transition", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("transition-pixelate", _pixelate)

    return runner.dispatch()
