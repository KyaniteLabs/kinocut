"""Image CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add image subcommands to the CLI parser."""
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
