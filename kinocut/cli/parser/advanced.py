"""Advanced CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add advanced subcommands to the CLI parser."""
    # batch
    batch_p = subparsers.add_parser("batch", help="Apply operation to multiple files")
    batch_p.add_argument("inputs", nargs="+", help="Input video files")
    batch_p.add_argument("-o", "--output-dir", help="Output directory for processed files")
    batch_p.add_argument(
        "--operation",
        required=True,
        choices=[
            "trim",
            "resize",
            "convert",
            "filter",
            "blur",
            "color_grade",
            "watermark",
            "speed",
            "fade",
            "normalize_audio",
        ],
        help="Operation to apply",
    )
    batch_p.add_argument("--params", help="Operation parameters as JSON")

    # detect-scenes
    scenes_p = subparsers.add_parser("detect-scenes", help="Detect scene changes in a video")
    scenes_p.add_argument("input", help="Input video file")
    scenes_p.add_argument(
        "-t", "--threshold", type=float, default=0.3, help="Detection sensitivity (0.0-1.0, default: 0.3)"
    )
    scenes_p.add_argument(
        "--min-duration", type=float, default=1.0, help="Minimum scene duration in seconds (default: 1.0)"
    )

    # create-from-images
    imgseq_p = subparsers.add_parser("create-from-images", help="Create video from image sequence")
    imgseq_p.add_argument("inputs", nargs="+", help="Input image files")
    imgseq_p.add_argument("-f", "--fps", type=float, default=30.0, help="Frames per second (default: 30)")
    imgseq_p.add_argument("-o", "--output", help="Output video file path")

    # export-frames
    frames_p = subparsers.add_parser("export-frames", help="Export video frames as images")
    frames_p.add_argument("input", help="Input video file")
    frames_p.add_argument("-o", "--output-dir", help="Output directory for frames")
    frames_p.add_argument("-f", "--fps", type=float, default=1.0, help="Frames per second to extract (default: 1)")
    frames_p.add_argument("--image-format", default="jpg", choices=["jpg", "png"], help="Image format (default: jpg)")

    # compare-quality
    quality_p = subparsers.add_parser("compare-quality", help="Compare video quality between two files")
    quality_p.add_argument("original", help="Original/reference video file")
    quality_p.add_argument("distorted", help="Processed/distorted video file")
    quality_p.add_argument(
        "--metrics", nargs="+", choices=["psnr", "ssim"], help="Metrics to compute (default: psnr ssim)"
    )

    # read-metadata
    read_meta_p = subparsers.add_parser("read-metadata", help="Read metadata tags from a file")
    read_meta_p.add_argument("input", help="Input video/audio file")

    # write-metadata
    write_meta_p = subparsers.add_parser("write-metadata", help="Write metadata tags to a file")
    write_meta_p.add_argument("input", help="Input video/audio file")
    write_meta_p.add_argument("--tags", required=True, help='Metadata as JSON, e.g. \'{"title": "My Video"}\'')
    write_meta_p.add_argument("-o", "--output", help="Output file path")

    # stabilize
    stab_p = subparsers.add_parser("stabilize", help="Stabilize a shaky video")
    stab_p.add_argument("input", help="Input video file")
    stab_p.add_argument("-s", "--smoothing", type=float, default=15, help="Smoothing strength (default: 15)")
    stab_p.add_argument("-z", "--zooming", type=float, default=0, help="Zoom to avoid black borders (default: 0)")
    stab_p.add_argument("-o", "--output", help="Output file path")

    # apply-mask
    mask_p = subparsers.add_parser("apply-mask", help="Apply an image mask to a video")
    mask_p.add_argument("input", help="Input video file")
    mask_p.add_argument("mask", help="Mask image file (white=visible, black=transparent)")
    mask_p.add_argument("--feather", type=int, default=5, help="Edge feather in pixels (default: 5)")
    mask_p.add_argument("-o", "--output", help="Output file path")

    # audio-waveform
    waveform_p = subparsers.add_parser("audio-waveform", help="Extract audio waveform data")
    waveform_p.add_argument("input", help="Input video/audio file")
    waveform_p.add_argument("-b", "--bins", type=int, default=50, help="Number of time segments (default: 50)")
    waveform_p.add_argument("-o", "--output", help="Output file path (optional, data is returned as JSON)")

    # generate-subtitles
    gen_subs_p = subparsers.add_parser("generate-subtitles", help="Generate SRT subtitles from text entries")
    gen_subs_p.add_argument("input", help="Input video file")
    gen_subs_p.add_argument(
        "--entries", required=True, help='Subtitle entries as JSON: \'[{"start":0,"end":2,"text":"Hello"}]\''
    )
    gen_subs_p.add_argument("--burn", action="store_true", help="Burn subtitles into video")
    gen_subs_p.add_argument("-o", "--output", help="Output directory/path (default: auto-generated)")
