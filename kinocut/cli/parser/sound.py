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
    voice.add_argument(
        "--request-json", default=None, help="SoundDubRequest JSON or file for real local caption speech"
    )
    voice.add_argument("--project-root", default=None, help="Explicit root for caption input and retained output")

    mix = subparsers.add_parser(
        "sound-mix-render",
        help="Assemble supplied WAVs into a new ZIP (omit inputs for a demo)",
    )
    mix.add_argument("--request-json", default=None, help="SoundMixRequest JSON or path to a JSON file")
    mix.add_argument("--project-root", default=None, help="Explicit local root for request media and output")
    master = subparsers.add_parser("sound-master-render", help="Retain a verified two-pass audio master")
    master.add_argument("--request-json", required=True, help="SoundMasterRequest JSON or file")
    master.add_argument("--project-root", required=True, help="Explicit root for source audio and new output ZIP")
    loudness = subparsers.add_parser(
        "sound-qa-loudness",
        help="Measure local audio and report actual loudness compliance",
    )
    loudness.add_argument("--request-json", default=None, help="SoundLoudnessRequest JSON or file")
    loudness.add_argument("--project-root", default=None, help="Explicit root for hashed audio input")

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
