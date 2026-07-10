"""Audio CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add audio subcommands to the CLI parser."""
    # normalize-audio
    norm_p = subparsers.add_parser("normalize-audio", help="Normalize audio loudness")
    norm_p.add_argument("input", help="Input video file")
    norm_p.add_argument("-l", "--lufs", type=float, default=-16.0, help="Target LUFS (default: -16 for YouTube)")
    norm_p.add_argument("--lra", type=float, help="Loudness Range target for broadcast compliance")
    norm_p.add_argument("-o", "--output", help="Output file path")

    # audio-synthesize
    asynth_p = subparsers.add_parser("audio-synthesize", help="Generate audio using waveform synthesis")
    asynth_p.add_argument("-o", "--output", required=True, help="Output WAV file path")
    asynth_p.add_argument(
        "-w",
        "--waveform",
        default="sine",
        choices=["sine", "square", "sawtooth", "triangle", "noise"],
        help="Waveform type (default: sine)",
    )
    asynth_p.add_argument("-f", "--frequency", type=float, default=440.0, help="Frequency in Hz (default: 440)")
    asynth_p.add_argument("-d", "--duration", type=float, default=1.0, help="Duration in seconds (default: 1.0)")
    asynth_p.add_argument("-v", "--volume", type=float, default=0.5, help="Volume 0-1 (default: 0.5)")
    asynth_p.add_argument("--effects", help='Effects as JSON, e.g. \'{"reverb": {"room_size": 0.5}}\'')

    # audio-compose
    acomp_p = subparsers.add_parser("audio-compose", help="Layer multiple audio tracks with mixing")
    acomp_p.add_argument("-o", "--output", required=True, help="Output WAV file path")
    acomp_p.add_argument("-d", "--duration", type=float, required=True, help="Total duration in seconds")
    acomp_p.add_argument(
        "--tracks", required=True, help="Tracks as JSON: [{'file': 'a.wav', 'volume': 0.5, 'start': 0}]"
    )

    # audio-preset
    apreset_p = subparsers.add_parser("audio-preset", help="Generate preset sound design elements")
    apreset_p.add_argument(
        "preset",
        help=(
            "Preset name: ui-blip, ui-click, ui-tap, ui-whoosh-up, ui-whoosh-down, "
            "drone-low, drone-mid, drone-tech, drone-ominous, chime-success, "
            "chime-error, chime-notification, typing, scan, processing, "
            "data-flow, upload, download"
        ),
    )
    apreset_p.add_argument("-o", "--output", required=True, help="Output WAV file path")
    apreset_p.add_argument(
        "--pitch", default="mid", choices=["low", "mid", "high"], help="Pitch variation (default: mid)"
    )
    apreset_p.add_argument("-d", "--duration", type=float, help="Override default duration (seconds)")
    apreset_p.add_argument("-i", "--intensity", type=float, default=0.5, help="Effect intensity 0-1 (default: 0.5)")

    # audio-sequence
    aseq_p = subparsers.add_parser("audio-sequence", help="Compose audio events into a timed sequence")
    aseq_p.add_argument("-o", "--output", required=True, help="Output WAV file path")
    aseq_p.add_argument(
        "--sequence", required=True, help="Sequence as JSON: [{'type': 'tone', 'at': 0, 'duration': 1, 'freq': 440}]"
    )

    # audio-effects
    aefx_p = subparsers.add_parser("audio-effects", help="Apply audio effects chain to a WAV file")
    aefx_p.add_argument("input", help="Input WAV file")
    aefx_p.add_argument("-o", "--output", required=True, help="Output WAV file path")
    aefx_p.add_argument("--effects", required=True, help="Effects as JSON: [{'type': 'lowpass', 'cutoff': 1000}]")

    # video-add-generated-audio
    addgen_p = subparsers.add_parser("video-add-generated-audio", help="Add procedurally generated audio to video")
    addgen_p.add_argument("input", help="Input video file")
    addgen_p.add_argument(
        "--audio-config", required=True, help='Audio config as JSON: {"drone": {"frequency": 100}, "events": [...]}'
    )
    addgen_p.add_argument("-o", "--output", help="Output file path")

    # video-audio-spatial
    aspat_p = subparsers.add_parser("video-audio-spatial", help="Apply 3D spatial audio positioning")
    aspat_p.add_argument("input", help="Input video file")
    aspat_p.add_argument("-o", "--output", help="Output file path")
    aspat_p.add_argument(
        "--positions", required=True, help='Positions as JSON: [{"time": 0, "azimuth": 0, "elevation": 0}]'
    )
    aspat_p.add_argument(
        "--method", default="hrtf", choices=["hrtf", "vbap", "simple"], help="Spatialization method (default: hrtf)"
    )
