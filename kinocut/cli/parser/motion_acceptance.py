"""Explicit whole-film human-attestation command, separate from inspection."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "record-motion-acceptance",
        help="Record explicit human motion review against exact source/report hashes",
        description=(
            "Record an authorized caller's whole-film viewing attestation. This is not "
            "system-verified viewing, model proof, or release approval. Do not invent human review."
        ),
    )
    parser.add_argument("input_path", help="The unchanged film inspected and viewed by the reviewer")
    report = parser.add_mutually_exclusive_group(required=True)
    report.add_argument("--report-json", help="Exact chronological motion report JSON (inline)")
    report.add_argument("--report-file", help="Exact motion report UTF-8 JSON file (bounded for longform reports)")
    parser.add_argument("--reviewer-id", required=True, help="Explicit human reviewer ID (human:<id>)")
    parser.add_argument("--source-sha256", required=True, help="Source hash explicitly reviewed by the caller")
    parser.add_argument("--report-sha256", required=True, help="Canonical digest of the exact reviewed report")
    watched = parser.add_mutually_exclusive_group(required=True)
    watched.add_argument("--watched-intervals-json", help="Explicit whole-film watched intervals JSON array")
    watched.add_argument("--watched-intervals-file", help="Bounded UTF-8 JSON watched intervals file")
    dispositions = parser.add_mutually_exclusive_group(required=True)
    dispositions.add_argument("--dispositions-json", help="Disposition for every flagged review ID, as JSON object")
    dispositions.add_argument("--dispositions-file", help="Bounded UTF-8 JSON dispositions file")
    parser.add_argument("--verdict", required=True, choices=("accept", "reject"))
