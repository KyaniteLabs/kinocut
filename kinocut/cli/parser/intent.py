"""CLI parsers for intent / watching / caption-translate surface."""

from __future__ import annotations

import argparse


def _add_intent_workflow_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register intent/workflow subcommands (intent routing, broll, translate, review, project, mutations)."""
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

    cfr = subparsers.add_parser("cutfile-render", help="Render a Cutfile via workflow engine")
    cfr.add_argument("path", help="cutfile.yaml or .json path")
    cfr.add_argument("-o", "--output", default=None, help="Output path relative to cutfile workspace")
    cfr.add_argument("--receipt", default=None, help="Receipt JSON path")
    cfr.add_argument("--keep-intermediates", action="store_true")

    mqc = subparsers.add_parser("metric-qc", help="Offline metric floor (duration/black/loudness)")
    mqc.add_argument("input", help="Media path")
    mqc.add_argument("--min-duration", type=float, default=0.5)
    mqc.add_argument("--max-black-ratio", type=float, default=0.95)

    mut_p = subparsers.add_parser("propose-mutations", help="Map findings JSON to typed proposed mutations")
    mut_p.add_argument("findings_json", help="Path to JSON list of findings")


def _add_media_tool_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register media-tool subcommands (QC, publish, hooks, seek, OTIO, sessions)."""
    subparsers.add_parser("qc-vision", help="Vision QC (graceful without VLM)").add_argument("input")
    subparsers.add_parser("qc-narrative", help="Narrative/first-15s QC").add_argument("input")

    pub = subparsers.add_parser("publish-validate", help="Validate platform publish specs (no upload)")
    pub.add_argument("platform")
    pub.add_argument("--duration", type=float, required=True)
    pub.add_argument("--height", type=int, required=True)
    pub.add_argument("--width", type=int, required=True)

    hk = subparsers.add_parser("hook-candidates", help="Hook title + thumb candidates (human pick)")
    hk.add_argument("topic")
    hk.add_argument("--count", type=int, default=5)
    hk.add_argument("--language", default="en")

    seek = subparsers.add_parser("seek-frame", help="Frame/timestamp conversion")
    seek.add_argument("--frame", type=int, default=None)
    seek.add_argument("--seconds", type=float, default=None)
    seek.add_argument("--fps", type=float, default=30.0)

    otio_e = subparsers.add_parser("otio-export", help="Export timeline JSON to OTIO JSON")
    otio_e.add_argument("timeline_json")
    otio_e.add_argument("-o", "--output", required=True)

    otio_i = subparsers.add_parser("otio-import", help="Import OTIO JSON to Timeline IR")
    otio_i.add_argument("path")

    subparsers.add_parser("review-ui", help="Write hot-reload review HTML").add_argument("output_dir")

    sess = subparsers.add_parser("edit-session", help="Open/step/close conversational edit session")
    sess.add_argument("action", choices=["open", "step", "close"])
    sess.add_argument("path")
    sess.add_argument("--goal", default="edit")
    sess.add_argument("--step-action", default="step")
    sess.add_argument("--score", type=float, default=None)
    sess.add_argument("--no-receipt", action="store_true", help="On close, skip writing receipt")


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register intent-related subcommands."""
    _add_intent_workflow_parsers(subparsers)
    _add_media_tool_parsers(subparsers)
