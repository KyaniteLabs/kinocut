"""Flat CLI parsers for the thin kinocut_sound S12 public join."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser(
        "sound-capabilities",
        help="Discover the bounded public sound operation set",
    )

    plan = subparsers.add_parser(
        "sound-plan-validate",
        help="Validate a SoundPlan JSON payload (or a built-in minimal plan)",
    )
    plan.add_argument(
        "--plan-json",
        default=None,
        help="SoundPlan as JSON string or path to a JSON file; omit for minimal plan",
    )

    voice = subparsers.add_parser(
        "sound-voice-batch",
        help="Render a local deterministic voice batch from a SoundPlan",
    )
    voice.add_argument(
        "--plan-json",
        default=None,
        help="SoundPlan as JSON string or path to a JSON file; omit for minimal plan",
    )

    subparsers.add_parser(
        "sound-mix-render",
        help="Render a bounded local mix for a minimal timeline",
    )
    subparsers.add_parser(
        "sound-qa-loudness",
        help="Measure loudness against the default delivery policy",
    )

    asr = subparsers.add_parser(
        "sound-qa-asr",
        help="Run the local fake ASR verification port against script hashes",
    )
    asr.add_argument(
        "--script-hashes",
        nargs="*",
        default=None,
        help="Optional script text hashes (sha256:…); default is a synthetic hash",
    )
    asr.add_argument(
        "--audio-duration-seconds",
        type=float,
        default=1.0,
        help="Audio duration in seconds for the fake ASR port (default 1.0)",
    )
