"""Media CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add media subcommands to the CLI parser."""
    # resize
    resize_p = subparsers.add_parser("resize", help="Resize a video")
    resize_p.add_argument("input", help="Input video file")
    resize_p.add_argument("-w", "--width", type=int, help="Target width")
    resize_p.add_argument("--height", type=int, help="Target height")
    resize_p.add_argument(
        "-a", "--aspect-ratio", choices=["16:9", "9:16", "1:1", "4:3", "4:5", "21:9"], help="Preset aspect ratio"
    )
    resize_p.add_argument("-q", "--quality", default="high", choices=["low", "medium", "high", "ultra"])
    resize_p.add_argument("-o", "--output", help="Output file path")

    # speed
    speed_p = subparsers.add_parser("speed", help="Change playback speed")
    speed_p.add_argument("input", help="Input video file")
    speed_p.add_argument("-f", "--factor", type=float, default=1.0, help="Speed multiplier (0.5=slow, 2.0=fast)")
    speed_p.add_argument("-o", "--output", help="Output file path")

    # convert
    convert_p = subparsers.add_parser("convert", help="Convert video format")
    convert_p.add_argument("input", help="Input video file")
    convert_p.add_argument(
        "-f",
        "--format",
        "--fmt",
        dest="fmt",
        default="mp4",
        choices=["mp4", "webm", "gif", "mov"],
        help="Output format",
    )
    convert_p.add_argument("-q", "--quality", default="high", choices=["low", "medium", "high", "ultra"])
    convert_p.add_argument("-o", "--output", help="Output file path")

    # thumbnail
    thumb_p = subparsers.add_parser("thumbnail", help="Extract a single frame")
    thumb_p.add_argument("input", help="Input video file")
    thumb_p.add_argument("-t", "--timestamp", type=float, help="Time in seconds (default: 10%% of duration)")
    thumb_p.add_argument("-o", "--output", help="Output image path")

    # preview
    preview_p = subparsers.add_parser("preview", help="Generate a fast low-res preview")
    preview_p.add_argument("input", help="Input video file")
    preview_p.add_argument("-o", "--output", help="Output file path")
    preview_p.add_argument("-s", "--scale", type=int, default=4, help="Downscale factor (default: 4)")

    # storyboard
    storyboard_p = subparsers.add_parser("storyboard", help="Extract key frames as storyboard")
    storyboard_p.add_argument("input", help="Input video file")
    storyboard_p.add_argument("-o", "--output-dir", help="Output directory")
    storyboard_p.add_argument("-n", "--frames", type=int, default=8, help="Number of frames (default: 8)")

    # subtitles
    subs_p = subparsers.add_parser("subtitles", help="Burn subtitles into video")
    subs_p.add_argument("input", help="Input video file")
    subs_p.add_argument("subtitle", help="Subtitle file (.srt or .vtt)")
    subs_p.add_argument(
        "--style", help="Subtitle style as FFmpeg force_style string (e.g. FontSize=24,PrimaryColour=&H00FFFFFF)"
    )
    subs_p.add_argument("-o", "--output", help="Output file path")

    # crop
    crop_p = subparsers.add_parser("crop", help="Crop a video to a region")
    crop_p.add_argument("input", help="Input video file")
    crop_p.add_argument("-w", "--width", type=int, required=True, help="Crop width in pixels")
    crop_p.add_argument("--height", type=int, required=True, help="Crop height in pixels")
    crop_p.add_argument("-x", type=int, default=None, help="X offset (default: center)")
    crop_p.add_argument("-y", type=int, default=None, help="Y offset (default: center)")
    crop_p.add_argument("-o", "--output", help="Output file path")

    # rotate
    rotate_p = subparsers.add_parser("rotate", help="Rotate and/or flip a video")
    rotate_p.add_argument("input", help="Input video file")
    rotate_p.add_argument(
        "-a", "--angle", type=int, default=0, choices=[0, 90, 180, 270], help="Rotation angle in degrees"
    )
    rotate_p.add_argument("--flip-h", action="store_true", help="Flip horizontally")
    rotate_p.add_argument("--flip-v", action="store_true", help="Flip vertically")
    rotate_p.add_argument("-o", "--output", help="Output file path")

    # fade
    fade_p = subparsers.add_parser("fade", help="Add fade in/out to video")
    fade_p.add_argument("input", help="Input video file")
    fade_p.add_argument("--fade-in", type=float, default=0.0, help="Fade in duration (seconds)")
    fade_p.add_argument("--fade-out", type=float, default=0.0, help="Fade out duration (seconds)")
    fade_p.add_argument("--crf", type=int, help="Override CRF value (0-51)")
    fade_p.add_argument(
        "--preset", choices=["ultrafast", "fast", "medium", "slow", "veryslow"], help="FFmpeg encoding preset"
    )
    fade_p.add_argument("-o", "--output", help="Output file path")

    # export
    export_p = subparsers.add_parser("export", help="Export video with quality settings")
    export_p.add_argument("input", help="Input video file")
    export_p.add_argument("-q", "--quality", default="high", choices=["low", "medium", "high", "ultra"])
    export_p.add_argument(
        "-f",
        "--format",
        "--fmt",
        dest="fmt",
        default="mp4",
        choices=["mp4", "webm", "gif", "mov"],
        help="Output format",
    )
    export_p.add_argument("-o", "--output", help="Output file path")

    # extract_audio
    extract_p = subparsers.add_parser("extract-audio", help="Extract audio from video")
    extract_p.add_argument("input", help="Input video file")
    extract_p.add_argument(
        "-f", "--format", "--fmt", dest="audio_format", default="mp3", choices=["mp3", "aac", "wav", "ogg", "flac"]
    )
    extract_p.add_argument("-o", "--output", help="Output audio file path")
