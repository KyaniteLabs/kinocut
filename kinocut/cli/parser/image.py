"""Image CLI subcommands."""

from __future__ import annotations

import argparse


def _add_image_analysis_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register image analysis subcommands (color extraction, palette, product analysis)."""
    # image-extract-colors
    imgcol_p = subparsers.add_parser("image-extract-colors", help="Extract dominant colors from an image")
    imgcol_p.add_argument("input", help="Input image file")
    imgcol_p.add_argument(
        "-n", "--n-colors", type=int, default=5, help="Number of colors to extract (default: 5, max: 20)"
    )

    # image-generate-palette
    imgpal_p = subparsers.add_parser("image-generate-palette", help="Generate color harmony palette from image")
    imgpal_p.add_argument("input", help="Input image file")
    imgpal_p.add_argument(
        "--harmony",
        default="complementary",
        choices=["complementary", "analogous", "triadic", "split_complementary"],
        help="Harmony type (default: complementary)",
    )
    imgpal_p.add_argument("-n", "--n-colors", type=int, default=5, help="Number of base colors (default: 5, max: 20)")

    # image-analyze-product
    imgprod_p = subparsers.add_parser(
        "image-analyze-product", help="Analyze a product image (colors + optional AI description)"
    )
    imgprod_p.add_argument("input", help="Input image file")
    imgprod_p.add_argument(
        "--use-ai", action="store_true", help="Use Claude Vision for description (requires ANTHROPIC_API_KEY)"
    )
    imgprod_p.add_argument(
        "-n", "--n-colors", type=int, default=5, help="Number of colors to extract (default: 5, max: 20)"
    )


def _add_still_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register still-workflow subcommands (match, grade, gate, edit, package)."""
    # still-match
    sm = subparsers.add_parser(
        "still-match",
        help="Match a package of stills to a hero plate with shared WB/exposure",
    )
    sm.add_argument("--hero", required=True, help="Hero/establish still path")
    sm.add_argument("--inputs", nargs="+", required=True, help="Input still paths")
    sm.add_argument("--output-dir", required=True, help="Directory for matched stills + receipt")

    # still-grade
    sg = subparsers.add_parser(
        "still-grade",
        help="Ordered still grade: correct→match→look (optional LUT last)",
    )
    sg.add_argument("--inputs", nargs="+", required=True, help="Input still paths")
    sg.add_argument("--output-dir", required=True, help="Output directory")
    sg.add_argument("--hero", help="Optional hero plate for match stage")
    sg.add_argument("--lut", dest="lut_path", help="Optional .cube/.3dl LUT applied last")
    sg.add_argument(
        "--signal-mode",
        action="store_true",
        help="Treat LUT as signal-alignment (not film look); log near-extrema preservation",
    )

    # still-gate
    sgate = subparsers.add_parser(
        "still-gate",
        help="Fail-closed cohesion gate + contact sheet for a still package",
    )
    sgate.add_argument("--inputs", nargs="+", required=True, help="Still package paths")
    sgate.add_argument("--output-dir", required=True, help="Directory for receipt + contact sheet")

    # image-edit (still-edit alias)
    se = subparsers.add_parser(
        "image-edit",
        help="Free establish-locked still edit with plan/receipt (prefer edit over paid gen)",
    )
    se.add_argument("--source", required=True, help="Source still")
    se.add_argument("--reference", required=True, help="Establish/reference still")
    se.add_argument("--intent", required=True, help="Edit intent text")
    se.add_argument("--output-dir", required=True, help="Output directory")
    se.add_argument("--prefer", default="edit", choices=["edit", "gen"], help="Cost policy (default: edit)")
    se.add_argument(
        "--allow-paid-gen",
        action="store_true",
        help="Explicitly allow paid generative backends (off by default)",
    )
    se.add_argument("--dry-run", action="store_true", help="Plan only; do not mutate pixels")

    # still-package
    sp = subparsers.add_parser(
        "still-package",
        help="Package workflow: edit beats → match → grade → cohesion gate",
    )
    sp.add_argument("--establish", required=True, help="Establish/hero still")
    sp.add_argument("--beats", nargs="+", required=True, help="Beat stills")
    sp.add_argument("--output-dir", required=True, help="Package output directory")
    sp.add_argument("--dry-run", action="store_true", help="Plan graph only")
    sp.add_argument("--lut", dest="lut_path", help="Optional signal LUT path")
    sp.add_argument("--signal-mode", action="store_true", help="Signal-alignment LUT mode")
    sp.add_argument("--no-grade", action="store_true", help="Skip grade stage after match")


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add image subcommands to the CLI parser."""
    _add_image_analysis_parsers(subparsers)
    _add_still_parsers(subparsers)
