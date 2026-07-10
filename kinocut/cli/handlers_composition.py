"""CLI handlers for motion graphics and layout commands."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg, _with_spinner
from .formatting import _format_composite_layers_text, _format_path_panel
from .runner import CommandRunner, _out


def handle_composition_command(args: Any, *, use_json: bool) -> bool:
    """Handle motion graphics and layout commands extracted from main."""
    runner = CommandRunner(args, use_json)

    def _text_animated(a, j):
        from ..effects_engine import text_animated

        r = _with_spinner(
            "Adding animated text...",
            text_animated,
            a.input,
            a.text,
            a.output,
            animation=a.animation,
            font=a.font,
            size=a.size,
            color=a.color,
            position=a.position,
            start=a.start,
            duration=a.duration,
            typewriter_speed=getattr(a, "typewriter_speed", 0.08),
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Animated text ({a.animation})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-text-animated", _text_animated)

    def _mograph_count(a, j):
        from ..effects_engine import mograph_count

        style = _parse_json_arg(a.style, "style", json_mode=j) if a.style else None
        r = _with_spinner(
            "Generating counter...", mograph_count, a.start, a.end, a.duration, a.output, style=style, fps=a.fps
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Counter ({a.start}-{a.end})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-mograph-count", _mograph_count)

    def _mograph_progress(a, j):
        from ..effects_engine import mograph_progress

        r = _with_spinner(
            "Generating progress animation...",
            mograph_progress,
            a.duration,
            a.output,
            style=a.style,
            color=a.color,
            track_color=a.track_color,
            fps=a.fps,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Progress bar ({a.style})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-mograph-progress", _mograph_progress)

    def _layout_grid(a, j):
        from ..effects_engine import layout_grid

        r = _with_spinner(
            "Creating grid layout...",
            layout_grid,
            a.inputs,
            a.layout,
            a.output,
            gap=a.gap,
            padding=a.padding,
            background=a.background,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Grid layout ({a.layout})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-layout-grid", _layout_grid)

    def _layout_pip(a, j):
        from ..effects_engine import layout_pip

        r = _with_spinner(
            "Creating PIP layout...",
            layout_pip,
            a.main,
            a.pip,
            a.output,
            position=a.position,
            size=a.size,
            margin=a.margin,
            border=a.border,
            border_color=a.border_color,
            border_width=a.border_width,
            rounded_corners=a.rounded_corners,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"PIP ({a.position})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-layout-pip", _layout_pip)

    def _composite_layers(a, j):
        from ..engine_composite_layers import composite_layers

        r = _with_spinner(
            "Compositing layers...",
            composite_layers,
            a.spec,
            output_path=a.output,
            save_layer_plan=a.save_layer_plan,
            dry_run=a.dry_run,
        )
        _out(
            r,
            j,
            _format_composite_layers_text,
            json_transform=lambda r: r.model_dump(),
        )

    runner.register("composite-layers", _composite_layers)

    return runner.dispatch()
