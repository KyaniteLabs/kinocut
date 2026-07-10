"""Ai CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add ai subcommands to the CLI parser."""
    # video-ai-transcribe
    aitrans_p = subparsers.add_parser("video-ai-transcribe", help="Transcribe speech to text using Whisper")
    aitrans_p.add_argument("input", help="Input video file")
    aitrans_p.add_argument("-o", "--output", help="Output SRT file path")
    aitrans_p.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model (default: base)",
    )
    aitrans_p.add_argument("--language", help="Language code (auto-detect if omitted)")

    # video-analyze
    analyze_p = subparsers.add_parser(
        "video-analyze",
        help="Comprehensive video analysis: transcript, metadata, scenes, audio, quality, chapters, colors",
    )
    analyze_p.add_argument("input", help="Input video file")
    analyze_p.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large", "turbo"],
        help="Whisper model (default: base)",
    )
    analyze_p.add_argument("--language", help="Language code for transcription (auto-detect if omitted)")
    analyze_p.add_argument(
        "--scene-threshold", type=float, default=0.3, help="Scene change sensitivity 0.0-1.0 (default: 0.3)"
    )
    analyze_p.add_argument("--no-transcript", action="store_true", help="Skip speech-to-text transcription")
    analyze_p.add_argument("--no-scenes", action="store_true", help="Skip scene detection")
    analyze_p.add_argument("--no-audio", action="store_true", help="Skip audio waveform analysis")
    analyze_p.add_argument("--no-quality", action="store_true", help="Skip visual quality check")
    analyze_p.add_argument("--no-chapters", action="store_true", help="Skip chapter generation")
    analyze_p.add_argument("--no-colors", action="store_true", help="Skip color extraction")
    analyze_p.add_argument("--output-srt", help="Write SRT subtitle file to this path")
    analyze_p.add_argument("--output-txt", help="Write plain-text transcript to this path")
    analyze_p.add_argument("--output-md", help="Write Markdown transcript to this path")
    analyze_p.add_argument("--output-json", help="Write full JSON transcript to this path")

    # video-ai-upscale
    aiup_p = subparsers.add_parser("video-ai-upscale", help="Upscale video using AI super-resolution")
    aiup_p.add_argument("input", help="Input video file")
    aiup_p.add_argument("-o", "--output", help="Output file path")
    aiup_p.add_argument("-s", "--scale", type=int, default=2, choices=[2, 4], help="Upscale factor (default: 2)")
    aiup_p.add_argument("--model", default="realesrgan", help="Model name (default: realesrgan)")

    # video-ai-stem-separation
    aistem_p = subparsers.add_parser("video-ai-stem-separation", help="Separate audio into stems using Demucs")
    aistem_p.add_argument("input", help="Input video file")
    aistem_p.add_argument("-o", "--output-dir", required=True, help="Output directory for stem files")
    aistem_p.add_argument("--stems", nargs="+", help="Stems to extract (default: vocals drums bass other)")
    aistem_p.add_argument("--model", default="htdemucs", help="Demucs model (default: htdemucs)")

    # video-ai-scene-detect
    aiscene_p = subparsers.add_parser("video-ai-scene-detect", help="Detect scene changes using perceptual hashing")
    aiscene_p.add_argument("input", help="Input video file")
    aiscene_p.add_argument("-t", "--threshold", type=float, default=0.3, help="Detection threshold (default: 0.3)")
    aiscene_p.add_argument("--use-ai", action="store_true", help="Use perceptual hashing for better accuracy")

    # video-ai-color-grade
    aigrade_p = subparsers.add_parser("video-ai-color-grade", help="Auto color grade video")
    aigrade_p.add_argument("input", help="Input video file")
    aigrade_p.add_argument("-o", "--output", help="Output file path")
    aigrade_p.add_argument("--reference", help="Reference video for color matching")
    aigrade_p.add_argument(
        "--style",
        default="auto",
        choices=["auto", "cinematic", "vintage", "warm", "cool", "dramatic"],
        help="Color style (default: auto)",
    )

    # video-ai-remove-silence
    airms_p = subparsers.add_parser("video-ai-remove-silence", help="Remove silent sections from video")
    airms_p.add_argument("input", help="Input video file")
    airms_p.add_argument("-o", "--output", help="Output file path")
    airms_p.add_argument("--silence-threshold", type=float, default=-50, help="Silence threshold in dB (default: -50)")
    airms_p.add_argument(
        "--min-silence-duration", type=float, default=0.5, help="Min silence duration in seconds (default: 0.5)"
    )
    airms_p.add_argument(
        "--keep-margin", type=float, default=0.1, help="Keep margin around silence in seconds (default: 0.1)"
    )
