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

    def _still_match(a, j):
        from ..still_plates import still_match

        r = _with_spinner(
            "Matching stills to hero...",
            still_match,
            hero=a.hero,
            inputs=list(a.inputs),
            output_dir=a.output_dir,
        )
        _out(r, j, lambda res: f"still-match ok → {res.get('output_dir')} ({len(res.get('outputs', []))} files)")

    runner.register("still-match", _still_match)

    def _still_grade(a, j):
        from ..still_plates import still_grade

        r = _with_spinner(
            "Grading stills...",
            still_grade,
            inputs=list(a.inputs),
            output_dir=a.output_dir,
            hero=getattr(a, "hero", None),
            lut_path=getattr(a, "lut_path", None),
            signal_mode=bool(getattr(a, "signal_mode", False)),
        )
        _out(r, j, lambda res: f"still-grade stages={res.get('stages')} → {res.get('output_dir')}")

    runner.register("still-grade", _still_grade)

    def _still_gate(a, j):
        from ..still_plates import still_gate

        r = _with_spinner(
            "Gating still package...",
            still_gate,
            inputs=list(a.inputs),
            output_dir=a.output_dir,
        )
        msg = f"still-gate {'PASS' if r.get('passed') else 'FAIL'} → {r.get('contact_sheet')}"
        _out(r, j, lambda res: msg)
        if not r.get("passed"):
            raise SystemExit(1)

    runner.register("still-gate", _still_gate)

    def _image_edit(a, j):
        from ..still_plates import image_edit

        r = _with_spinner(
            "Editing still toward establish...",
            image_edit,
            source=a.source,
            reference=a.reference,
            intent=a.intent,
            output_dir=a.output_dir,
            prefer=getattr(a, "prefer", "edit"),
            allow_paid_gen=bool(getattr(a, "allow_paid_gen", False)),
            dry_run=bool(getattr(a, "dry_run", False)),
        )
        _out(r, j, lambda res: f"image-edit {res.get('status')} dry_run={res.get('dry_run')}")

    runner.register("image-edit", _image_edit)

    def _still_package(a, j):
        from ..still_plates import still_package

        r = _with_spinner(
            "Running still package workflow...",
            still_package,
            establish=a.establish,
            beats=list(a.beats),
            output_dir=a.output_dir,
            apply_grade=not bool(getattr(a, "no_grade", False)),
            lut_path=getattr(a, "lut_path", None),
            signal_mode=bool(getattr(a, "signal_mode", False)),
            dry_run=bool(getattr(a, "dry_run", False)),
        )
        _out(r, j, lambda res: f"still-package {res.get('status')} → {res.get('output_dir')}")
        if not r.get("dry_run") and not r.get("passed", True):
            raise SystemExit(1)

    runner.register("still-package", _still_package)

    return runner.dispatch()
