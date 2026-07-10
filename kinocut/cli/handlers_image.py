"""CLI handlers for image analysis commands."""

from __future__ import annotations

from typing import Any

from .common import _with_spinner
from .formatting import (
    _format_analyze_product,
    _format_extract_colors,
    _format_generate_palette,
)
from .runner import CommandRunner, _out


def handle_image_commands(args: Any, *, use_json: bool) -> bool:
    """Handle image analysis commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _extract_colors(a, j):
        from ..image_engine import extract_colors

        r = _with_spinner("Extracting colors...", extract_colors, a.input, n_colors=a.n_colors)
        _out(
            r,
            j,
            _format_extract_colors,
            json_transform=lambda res: res.model_dump() if hasattr(res, "model_dump") else res,
        )

    runner.register("image-extract-colors", _extract_colors)

    def _generate_palette(a, j):
        from ..image_engine import generate_palette

        r = _with_spinner("Generating palette...", generate_palette, a.input, harmony=a.harmony, n_colors=a.n_colors)
        _out(
            r,
            j,
            lambda res: _format_generate_palette(res, a.harmony),
            json_transform=lambda res: res.model_dump() if hasattr(res, "model_dump") else res,
        )

    runner.register("image-generate-palette", _generate_palette)

    def _analyze_product(a, j):
        from ..image_engine import analyze_product

        r = _with_spinner("Analyzing product...", analyze_product, a.input, use_ai=a.use_ai, n_colors=a.n_colors)
        _out(
            r,
            j,
            _format_analyze_product,
            json_transform=lambda res: res.model_dump() if hasattr(res, "model_dump") else res,
        )

    runner.register("image-analyze-product", _analyze_product)

    return runner.dispatch()
