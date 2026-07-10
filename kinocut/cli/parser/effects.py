"""Effects CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add effects subcommands to the CLI parser."""
    # add_text
    text_p = subparsers.add_parser("add-text", help="Overlay text on a video")
    text_p.add_argument("input", help="Input video file")
    text_p.add_argument("text", help="Text to overlay")
    text_p.add_argument(
        "-p",
        "--position",
        default="top-center",
        choices=[
            "top-left",
            "top-center",
            "top-right",
            "center-left",
            "center",
            "center-right",
            "bottom-left",
            "bottom-center",
            "bottom-right",
        ],
    )
    text_p.add_argument("--font", help="Path to font file")
    text_p.add_argument("--size", type=int, default=48, help="Font size in pixels")
    text_p.add_argument("--color", default="white", help="Text color")
    text_p.add_argument("--no-shadow", action="store_true", help="Disable text shadow")
    text_p.add_argument("--start-time", type=float, help="When text appears (seconds)")
    text_p.add_argument("--duration", type=float, help="How long text is visible (seconds)")
    text_p.add_argument("-o", "--output", help="Output file path")

    # add_audio
    audio_p = subparsers.add_parser("add-audio", help="Add or replace audio track")
    audio_p.add_argument("video", help="Input video file")
    audio_p.add_argument("audio", help="Audio file (MP3, WAV, etc.)")
    audio_p.add_argument("-v", "--volume", type=float, default=1.0, help="Audio volume (0.0-2.0)")
    audio_p.add_argument("--fade-in", type=float, default=0.0, help="Fade in duration")
    audio_p.add_argument("--fade-out", type=float, default=0.0, help="Fade out duration")
    audio_p.add_argument("--mix", action="store_true", help="Mix with existing audio instead of replacing")
    audio_p.add_argument("--start-time", type=float, help="When audio starts (seconds)")
    audio_p.add_argument("-o", "--output", help="Output file path")

    # watermark
    wm_p = subparsers.add_parser("watermark", help="Add image watermark")
    wm_p.add_argument("input", help="Input video file")
    wm_p.add_argument("image", help="Watermark image (PNG recommended)")
    wm_p.add_argument(
        "-p",
        "--position",
        default="bottom-right",
        choices=[
            "top-left",
            "top-center",
            "top-right",
            "center-left",
            "center",
            "bottom-left",
            "bottom-center",
            "bottom-right",
        ],
    )
    wm_p.add_argument("--opacity", type=float, default=0.7, help="Watermark opacity (0.0-1.0)")
    wm_p.add_argument("--margin", type=int, default=20, help="Margin from edge in pixels")
    wm_p.add_argument("--crf", type=int, help="Override CRF value (0-51)")
    wm_p.add_argument(
        "--preset", choices=["ultrafast", "fast", "medium", "slow", "veryslow"], help="FFmpeg encoding preset"
    )
    wm_p.add_argument("-o", "--output", help="Output file path")

    # filter
    filter_p = subparsers.add_parser("filter", help="Apply a visual filter")
    filter_p.add_argument("input", help="Input video file")
    filter_p.add_argument(
        "-t",
        "--type",
        dest="filter_type",
        required=True,
        choices=[
            "blur",
            "sharpen",
            "brightness",
            "contrast",
            "saturation",
            "grayscale",
            "sepia",
            "invert",
            "vignette",
            "color_preset",
            "denoise",
            "deinterlace",
            "ken_burns",
            "reverb",
            "compressor",
            "pitch_shift",
            "noise_reduction",
        ],
        help="Filter type",
    )
    filter_p.add_argument("--params", help="Filter parameters as JSON")
    filter_p.add_argument("--crf", type=int, help="Override CRF value (0-51)")
    filter_p.add_argument(
        "--preset", choices=["ultrafast", "fast", "medium", "slow", "veryslow"], help="FFmpeg encoding preset"
    )
    filter_p.add_argument("-o", "--output", help="Output file path")

    # reverse
    reverse_p = subparsers.add_parser("reverse", help="Reverse video playback")
    reverse_p.add_argument("input", help="Input video file")
    reverse_p.add_argument("-o", "--output", help="Output file path")

    # chroma-key
    chroma_p = subparsers.add_parser("chroma-key", help="Remove solid color background (green screen)")
    chroma_p.add_argument("input", help="Input video file")
    chroma_p.add_argument("--color", default="0x00FF00", help="Color to remove in hex (default: 0x00FF00 for green)")
    chroma_p.add_argument("--similarity", type=float, default=0.01, help="Color similarity threshold (default: 0.01)")
    chroma_p.add_argument("--blend", type=float, default=0.0, help="Blend amount (default: 0.0)")
    chroma_p.add_argument("-o", "--output", help="Output file path")

    # overlay-video
    overlay_p = subparsers.add_parser("overlay-video", help="Picture-in-picture overlay")
    overlay_p.add_argument("background", help="Background video file")
    overlay_p.add_argument("overlay", help="Overlay video file")
    overlay_p.add_argument(
        "-p",
        "--position",
        default="top-right",
        choices=[
            "top-left",
            "top-center",
            "top-right",
            "center-left",
            "center",
            "center-right",
            "bottom-left",
            "bottom-center",
            "bottom-right",
        ],
    )
    overlay_p.add_argument("-w", "--width", type=int, help="Overlay width")
    overlay_p.add_argument("--height", type=int, help="Overlay height")
    overlay_p.add_argument("--opacity", type=float, default=0.8, help="Overlay opacity (0.0-1.0)")
    overlay_p.add_argument("--start-time", type=float, help="When overlay appears (seconds)")
    overlay_p.add_argument("--duration", type=float, help="How long overlay is visible (seconds)")
    overlay_p.add_argument("--crf", type=int, help="Override CRF value (0-51)")
    overlay_p.add_argument(
        "--preset", choices=["ultrafast", "fast", "medium", "slow", "veryslow"], help="FFmpeg encoding preset"
    )
    overlay_p.add_argument("-o", "--output", help="Output file path")

    # split-screen
    split_p = subparsers.add_parser("split-screen", help="Place two videos side by side or top/bottom")
    split_p.add_argument("left", help="First video file")
    split_p.add_argument("right", help="Second video file")
    split_p.add_argument(
        "-l", "--layout", default="side-by-side", choices=["side-by-side", "top-bottom"], help="Layout type"
    )
    split_p.add_argument("-o", "--output", help="Output file path")

    # effect-vignette
    vig_p = subparsers.add_parser("effect-vignette", help="Apply vignette effect (darkened edges)")
    vig_p.add_argument("input", help="Input video file")
    vig_p.add_argument("-o", "--output", help="Output file path")
    vig_p.add_argument("-i", "--intensity", type=float, default=0.5, help="Darkness amount 0-1 (default: 0.5)")
    vig_p.add_argument("-r", "--radius", type=float, default=0.8, help="Vignette radius 0-1 (default: 0.8)")
    vig_p.add_argument("-s", "--smoothness", type=float, default=0.5, help="Edge softness 0-1 (default: 0.5)")

    # effect-glow
    glow_p = subparsers.add_parser("effect-glow", help="Apply bloom/glow effect to highlights")
    glow_p.add_argument("input", help="Input video file")
    glow_p.add_argument("-o", "--output", help="Output file path")
    glow_p.add_argument("-i", "--intensity", type=float, default=0.5, help="Glow strength 0-1 (default: 0.5)")
    glow_p.add_argument("-r", "--radius", type=int, default=10, help="Blur radius in pixels (default: 10)")
    glow_p.add_argument("-t", "--threshold", type=float, default=0.7, help="Brightness threshold 0-1 (default: 0.7)")

    # effect-noise
    noise_p = subparsers.add_parser("effect-noise", help="Apply film grain or digital noise")
    noise_p.add_argument("input", help="Input video file")
    noise_p.add_argument("-o", "--output", help="Output file path")
    noise_p.add_argument("-i", "--intensity", type=float, default=0.05, help="Noise amount 0-1 (default: 0.05)")
    noise_p.add_argument(
        "-m", "--mode", default="film", choices=["film", "digital", "color"], help="Noise type (default: film)"
    )
    noise_p.add_argument("--static", action="store_true", help="Use static noise instead of animated")

    # effect-scanlines
    scan_p = subparsers.add_parser("effect-scanlines", help="Apply CRT-style scanlines overlay")
    scan_p.add_argument("input", help="Input video file")
    scan_p.add_argument("-o", "--output", help="Output file path")
    scan_p.add_argument("--line-height", type=int, default=2, help="Pixels per scanline (default: 2)")
    scan_p.add_argument("--opacity", type=float, default=0.3, help="Line opacity 0-1 (default: 0.3)")
    scan_p.add_argument("--flicker", type=float, default=0.1, help="Brightness variation 0-1 (default: 0.1)")

    # effect-chromatic-aberration
    chroma_p = subparsers.add_parser("effect-chromatic-aberration", help="Apply RGB channel separation")
    chroma_p.add_argument("input", help="Input video file")
    chroma_p.add_argument("-o", "--output", help="Output file path")
    chroma_p.add_argument("-i", "--intensity", type=float, default=2.0, help="Pixel offset amount (default: 2.0)")
    chroma_p.add_argument("-a", "--angle", type=float, default=0, help="Separation direction in degrees (default: 0)")

    # transition-glitch
    tglitch_p = subparsers.add_parser("transition-glitch", help="Apply glitch transition between two clips")
    tglitch_p.add_argument("clip1", help="First video clip")
    tglitch_p.add_argument("clip2", help="Second video clip")
    tglitch_p.add_argument("-o", "--output", help="Output file path")
    tglitch_p.add_argument(
        "-d", "--duration", type=float, default=0.5, help="Transition duration in seconds (default: 0.5)"
    )
    tglitch_p.add_argument("-i", "--intensity", type=float, default=0.3, help="Glitch intensity 0-1 (default: 0.3)")

    # transition-morph
    tmorph_p = subparsers.add_parser("transition-morph", help="Apply morph transition between two clips")
    tmorph_p.add_argument("clip1", help="First video clip")
    tmorph_p.add_argument("clip2", help="Second video clip")
    tmorph_p.add_argument("-o", "--output", help="Output file path")
    tmorph_p.add_argument(
        "-d", "--duration", type=float, default=0.6, help="Transition duration in seconds (default: 0.6)"
    )
    tmorph_p.add_argument("--mesh-size", type=int, default=10, help="Mesh warp intensity (default: 10)")

    # transition-pixelate
    tpxl_p = subparsers.add_parser("transition-pixelate", help="Apply pixelate transition between two clips")
    tpxl_p.add_argument("clip1", help="First video clip")
    tpxl_p.add_argument("clip2", help="Second video clip")
    tpxl_p.add_argument("-o", "--output", help="Output file path")
    tpxl_p.add_argument(
        "-d", "--duration", type=float, default=0.4, help="Transition duration in seconds (default: 0.4)"
    )
    tpxl_p.add_argument("--pixel-size", type=int, default=50, help="Pixel size (default: 50)")
