"""CLI parser for the `kino shorts` long-form-to-verticals orchestrator.

The orchestrator business logic lives in :mod:`kinocut.product.shorts`; this
module is a thin argparse adapter that registers the canonical command and
documents every flag with plain-language help (no engine / model jargon). The
default mode stops after proposals: nothing is rendered until the operator
explicitly approves a rendered run through the orchestrator.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


#: Default platforms produced when the operator does not pass ``--platform``.
#: Mirror of ``kinocut.product.config.CANONICAL_EXTERNAL_PLATFORMS``; kept as
#: a constant here so the parser does not import the product module (which is
#: optional at install time).
DEFAULT_PLATFORMS: tuple[str, ...] = ("youtube-shorts", "instagram-reel")


def _platform_choices() -> Sequence[str]:
    """Return the bounded platform set the CLI accepts."""
    return ("youtube-shorts", "instagram-reel")


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``shorts`` subparser.

    The parser is intentionally conservative: every knob is keyword-only on
    ``shorts_plan`` and ``shorts_review``; flags mirror those names so the
    orchestrator's error messages can refer to "the same flag name" without
    the CLI renaming anything. The default behaviour proposes clips but does
    not render any media; ``--decisions`` is the only path that mutates review
    state.
    """

    parser = subparsers.add_parser(
        "shorts",
        help="Propose vertical clips from a long-form video (no render by default)",
        description=(
            "Build a reviewable proposal of vertical clips from a long-form "
            "source. By default the command stops after proposals — no media "
            "is rendered. Pass --decisions <path> to record human review "
            "choices against the proposals; render runs only via the explicit "
            "orchestrator entrypoint."
        ),
        epilog=(
            "Plain-language summary: this command analyses a long-form source, "
            "suggests vertical clip candidates for each platform, writes a "
            "review manifest, and stops. Review the manifest, record "
            "decisions, then run the orchestrator's render entrypoint if you "
            "choose to produce any media. No credentials, no posting."
        ),
    )

    parser.add_argument(
        "input",
        help="Path to the source long-form video file",
    )

    parser.add_argument(
        "--platform",
        action="append",
        default=None,
        choices=_platform_choices(),
        metavar="NAME",
        help=(
            "Vertical platform to include in the proposal "
            "(youtube-shorts or instagram-reel). Repeat to include multiple. "
            "Defaults to both when omitted."
        ),
    )

    parser.add_argument(
        "--max-clip-seconds",
        type=float,
        default=None,
        help=(
            "Optional upper bound on each proposed clip length, in seconds. "
            "Each platform already enforces its own maximum; this tightens it "
            "if needed."
        ),
    )

    parser.add_argument(
        "--min-clip-seconds",
        type=float,
        default=None,
        help=(
            "Optional lower bound on each proposed clip length, in seconds. "
            "Moments shorter than this are dropped from the proposal."
        ),
    )

    parser.add_argument(
        "--subject-reframe",
        action="store_true",
        help=(
            "When set, propose a reframed vertical layout that re-centres on a "
            "detected subject (off by default). Subject detection runs locally; "
            "no model download is required."
        ),
    )

    burned_captions = parser.add_mutually_exclusive_group()
    burned_captions.add_argument(
        "--burned-captions",
        action="store_true",
        dest="burned_captions",
        default=None,
        help="Burn captions into the proposed vertical clips (off by default).",
    )
    burned_captions.add_argument(
        "--no-burned-captions",
        action="store_false",
        dest="burned_captions",
        help="Leave captions as a separate, editable sidecar instead of burning them.",
    )

    parser.add_argument(
        "--captions-editable",
        action="store_true",
        default=True,
        help=("Include the required editable SRT caption sidecar in every package (enabled by default)."),
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional directory for the proposal manifest and sidecar captions. "
            "Created if it does not exist. Omit to keep the proposal in-memory "
            "only (the response still includes the manifest path)."
        ),
    )

    parser.add_argument(
        "--resume-job-id",
        default=None,
        metavar="ID",
        help=(
            "Optional job identifier from a prior proposal. When set, the "
            "command re-hydrates the prior plan from the project store instead "
            "of re-running discovery."
        ),
    )

    parser.add_argument(
        "--decisions",
        default=None,
        metavar="PATH",
        help=(
            "Optional path to a UTF-8 JSON file of human review decisions "
            "against a prior proposal. With this flag the command records the "
            "decisions and stops — it does not render any media."
        ),
    )
