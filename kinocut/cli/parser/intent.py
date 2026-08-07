"""CLI parsers for intent / watching / caption-translate surface."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register intent-related subcommands."""
    intent_p = subparsers.add_parser("intent", help="Route a semantic intent verb to a plan")
    intent_p.add_argument("verb", nargs="?", default=None, help="Intent verb (omit with --list)")
    intent_p.add_argument("--list", action="store_true", help="List known intent verbs")
    intent_p.add_argument("--params-json", default=None, help="Optional JSON object of verb params")

    broll_p = subparsers.add_parser(
        "propose-broll",
        help="Propose transcript-keyed b-roll inserts (never silent apply)",
    )
    broll_p.add_argument("segments_json", help="Path to JSON list of {start,end,text} segments")
    broll_p.add_argument("--max", type=int, default=8, dest="max_proposals")

    tr_p = subparsers.add_parser("translate-captions", help="Translate SRT captions (EN→ES first)")
    tr_p.add_argument("input", help="Input .srt path")
    tr_p.add_argument("-o", "--output", help="Output .srt path")
    tr_p.add_argument("--source-lang", default="en")
    tr_p.add_argument("--target-lang", default="es")

    subparsers.add_parser("language-coverage", help="Honest transcribe/translate/dub coverage matrix")

    rev_p = subparsers.add_parser("review-run", help="Run offline watching metric floor on a media file")
    rev_p.add_argument("input", help="Input video path")

    dec_p = subparsers.add_parser("review-decide", help="Record human decision on a review_run JSON file")
    dec_p.add_argument("review_run_json", help="Path to review_run JSON artifact")
    dec_p.add_argument("decision", choices=["accept", "reject", "revise"])
    dec_p.add_argument("--reason", default="")

    init_p = subparsers.add_parser("init", help="Scaffold a local Kinocut project directory")
    init_p.add_argument("path", help="Project directory path")
    init_p.add_argument("--name", default=None)
    init_p.add_argument("--no-cutfile", action="store_true")

    est_p = subparsers.add_parser("estimate", help="Dry-run local time/cost-unit estimate for an operation")
    est_p.add_argument("operation", help="Operation name (trim, repurpose, …)")
    est_p.add_argument("--duration", type=float, required=True, help="Media duration seconds")
    est_p.add_argument("--complexity", type=float, default=1.0)

    bk_p = subparsers.add_parser("brand-kit", help="Save or load a brand kit JSON")
    bk_p.add_argument("action", choices=["save", "load"])
    bk_p.add_argument("path", help="Brand kit JSON path")
    bk_p.add_argument("--name", default="brand")
    bk_p.add_argument("--primary", default="#FFFFFF")
    bk_p.add_argument("--accent", default="#000000")

    cf_p = subparsers.add_parser("cutfile-validate", help="Validate a Cutfile")
    cf_p.add_argument("path", help="cutfile.yaml or .json path")

    mut_p = subparsers.add_parser("propose-mutations", help="Map findings JSON to typed proposed mutations")
    mut_p.add_argument("findings_json", help="Path to JSON list of findings")
