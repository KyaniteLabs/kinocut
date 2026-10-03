"""Plain-file audio mixing and sidechain ducking CLI arguments."""

from __future__ import annotations

import argparse

from ...defaults import (
    DEFAULT_AUDIO_MIX_BITRATE,
    DEFAULT_DUCK_ATTACK_MS,
    DEFAULT_DUCK_MUSIC_VOLUME,
    DEFAULT_DUCK_RATIO,
    DEFAULT_DUCK_RELEASE_MS,
    DEFAULT_DUCK_THRESHOLD,
)


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add mix-audio and duck-audio without changing existing commands."""
    mix = subparsers.add_parser("mix-audio", help="Mix timed sounds with one AAC encode; copy picture")
    mix.add_argument("input", help="Input video path")
    mix.add_argument(
        "--sounds", "--tracks", required=True, help="JSON track array: path, start, volume, fade_in, fade_out"
    )
    mix.add_argument(
        "--keep-source", action=argparse.BooleanOptionalAction, default=True, help="Keep existing video audio"
    )
    mix.add_argument("--audio-bitrate", default=DEFAULT_AUDIO_MIX_BITRATE, help="AAC bitrate, e.g. 256k")
    mix.add_argument("-o", "--output", help="Output path (auto-generated if omitted)")
    duck = subparsers.add_parser("duck-audio", help="Duck background music under the video's existing voice")
    duck.add_argument("input", help="Input video path with audio")
    duck.add_argument("music", help="Music audio/video path")
    duck.add_argument("-o", "--output", help="Output path (auto-generated if omitted)")
    duck.add_argument("--music-volume", type=float, default=DEFAULT_DUCK_MUSIC_VOLUME)
    duck.add_argument("--threshold", type=float, default=DEFAULT_DUCK_THRESHOLD)
    duck.add_argument("--ratio", type=float, default=DEFAULT_DUCK_RATIO)
    duck.add_argument("--attack", type=float, default=DEFAULT_DUCK_ATTACK_MS, help="Attack milliseconds")
    duck.add_argument("--release", type=float, default=DEFAULT_DUCK_RELEASE_MS, help="Release milliseconds")
