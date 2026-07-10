"""Hyperframes CLI subcommands."""

from __future__ import annotations

import argparse


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Add Hyperframes subcommands to the CLI parser."""
    # hyperframes-render
    hyperframes_render_p = subparsers.add_parser("hyperframes-render", help="Render a Hyperframes composition to video")
    hyperframes_render_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_render_p.add_argument("-o", "--output", help="Output video file path")
    hyperframes_render_p.add_argument("--fps", type=float, help="Frame rate (24, 30, 60)")
    hyperframes_render_p.add_argument("--width", type=int, help="Output width in pixels")
    hyperframes_render_p.add_argument("--height", type=int, help="Output height in pixels")
    hyperframes_render_p.add_argument("-c", "--composition", help="Composition file to render instead of index.html")
    hyperframes_render_p.add_argument(
        "--resolution",
        choices=["landscape", "portrait", "landscape-4k", "portrait-4k", "1080p", "4k", "uhd"],
        help="Output resolution preset",
    )
    hyperframes_render_p.add_argument(
        "--quality",
        default="standard",
        choices=["draft", "standard", "high"],
        help="Render quality (default: standard)",
    )
    hyperframes_render_p.add_argument(
        "--format",
        dest="output_format",
        default="mp4",
        choices=["mp4", "webm", "mov", "png-sequence"],
        help="Output format (default: mp4)",
    )
    hyperframes_render_p.add_argument("--workers", help="Parallel render workers (number or 'auto')")
    hyperframes_render_p.add_argument("--crf", type=int, help="Override encoder CRF")
    hyperframes_render_p.add_argument("--variables", help="Inline JSON runtime data for the composition")
    hyperframes_render_p.add_argument("--variables-file", help="Path to JSON runtime data for the composition")

    # hyperframes-compositions
    hyperframes_comps_p = subparsers.add_parser(
        "hyperframes-compositions", help="List compositions in a Hyperframes project"
    )
    hyperframes_comps_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_comps_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # hyperframes-preview
    hyperframes_preview_p = subparsers.add_parser("hyperframes-preview", help="Launch Hyperframes preview studio")
    hyperframes_preview_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_preview_p.add_argument("-p", "--port", type=int, default=3002, help="Preview port (default: 3002)")
    hyperframes_preview_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # hyperframes-still
    hyperframes_still_p = subparsers.add_parser("hyperframes-still", help="Render a single frame as image")
    hyperframes_still_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_still_p.add_argument("-o", "--output", help="Output image file path")
    hyperframes_still_p.add_argument("--frame", type=int, default=0, help="Frame number to render (default: 0)")
    hyperframes_still_p.add_argument("--variables", help="Inline JSON runtime data for the composition")
    hyperframes_still_p.add_argument("--variables-file", help="Path to JSON runtime data for the composition")

    snapshot_p = subparsers.add_parser("hyperframes-snapshot", help="Capture key frames as PNG screenshots")
    snapshot_p.add_argument("project_path", help="Path to Hyperframes project")
    snapshot_p.add_argument("--frames", type=int, default=5, help="Number of evenly-spaced frames")
    snapshot_p.add_argument("--at", nargs="+", type=float, help="Specific timestamps in seconds")
    snapshot_p.add_argument("--variables", help="Inline JSON runtime data for the composition")
    snapshot_p.add_argument("--variables-file", help="Path to JSON runtime data for the composition")

    inspect_p = subparsers.add_parser("hyperframes-inspect", help="Inspect Hyperframes layout overflow")
    inspect_p.add_argument("project_path", help="Path to Hyperframes project")
    inspect_p.add_argument("--samples", type=int, default=9)
    inspect_p.add_argument("--strict", action="store_true")

    catalog_p = subparsers.add_parser("hyperframes-catalog", help="Browse Hyperframes catalog")
    catalog_p.add_argument("--tag")
    catalog_p.add_argument("--type", dest="item_type", choices=["block", "component"])

    info_p = subparsers.add_parser("hyperframes-info", help="Show Hyperframes project metadata")
    info_p.add_argument("project_path", help="Path to Hyperframes project")

    capture_p = subparsers.add_parser("hyperframes-capture", help="Capture a website as Hyperframes components")
    capture_p.add_argument("url", help="Website URL")
    capture_p.add_argument("-o", "--output", help="Output directory")
    capture_p.add_argument("--skip-assets", action="store_true")

    tts_p = subparsers.add_parser("hyperframes-tts", help="Generate speech audio with Hyperframes TTS")
    tts_p.add_argument("text_or_file", help="Text to speak or path to .txt")
    tts_p.add_argument("-o", "--output", help="Output audio file")
    tts_p.add_argument("--voice")
    tts_p.add_argument("--speed", type=float)

    transcribe_p = subparsers.add_parser("hyperframes-transcribe", help="Transcribe media with Hyperframes")
    transcribe_p.add_argument("input_path", help="Audio/video/transcript input")
    transcribe_p.add_argument("-d", "--project-path")
    transcribe_p.add_argument("-m", "--model")
    transcribe_p.add_argument("-l", "--language")

    remove_bg_p = subparsers.add_parser("hyperframes-remove-background", help="Remove image/video background")
    remove_bg_p.add_argument("input_path", help="Input image/video")
    remove_bg_p.add_argument("-o", "--output", help="Output file path")
    remove_bg_p.add_argument("--background-output")
    remove_bg_p.add_argument("--device", default="auto", choices=["auto", "cpu", "coreml", "cuda"])
    remove_bg_p.add_argument("--quality", default="balanced", choices=["fast", "balanced", "best"])

    subparsers.add_parser("hyperframes-doctor", help="Run Hyperframes diagnostics")

    benchmark_p = subparsers.add_parser("hyperframes-benchmark", help="Benchmark Hyperframes rendering")
    benchmark_p.add_argument("project_path", help="Path to Hyperframes project")
    benchmark_p.add_argument("-o", "--output", help="Output path")
    benchmark_p.add_argument("--runs", type=int, help="Number of runs per config")

    # hyperframes-init
    hyperframes_init_p = subparsers.add_parser("hyperframes-init", help="Scaffold a new Hyperframes project")
    hyperframes_init_p.add_argument("name", help="Project name")
    hyperframes_init_p.add_argument("-d", "--output-dir", help="Output directory (default: current directory)")
    hyperframes_init_p.add_argument(
        "-t",
        "--template",
        default="blank",
        choices=["blank", "warm-grain", "swiss-grid"],
        help="Project template (default: blank)",
    )
    hyperframes_init_p.add_argument("--video", help="Source video for project bootstrap")
    hyperframes_init_p.add_argument("--audio", help="Source audio for project bootstrap")
    hyperframes_init_p.add_argument("--skip-transcribe", action="store_true", help="Skip Whisper transcription")
    hyperframes_init_p.add_argument("--model", help="Whisper model for transcription")
    hyperframes_init_p.add_argument("--language", help="Language code for transcription")
    hyperframes_init_p.add_argument("--tailwind", action="store_true", help="Add Tailwind CSS browser-runtime support")
    hyperframes_init_p.add_argument(
        "--resolution",
        choices=["landscape", "portrait", "landscape-4k", "portrait-4k", "1080p", "4k", "uhd"],
        help="Canvas resolution preset",
    )

    # hyperframes-add-block
    hyperframes_add_p = subparsers.add_parser(
        "hyperframes-add-block", help="Install a block from the Hyperframes catalog"
    )
    hyperframes_add_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_add_p.add_argument("block_name", help="Registry item name (e.g. claude-code-window, shader-wipe)")
    hyperframes_add_p.add_argument("--no-clipboard", action="store_true", help="Skip copying include snippet")

    # hyperframes-validate
    hyperframes_validate_p = subparsers.add_parser("hyperframes-validate", help="Validate a Hyperframes project")
    hyperframes_validate_p.add_argument("project_path", help="Path to Hyperframes project")

    # hyperframes-pipeline
    hyperframes_pipeline_p = subparsers.add_parser("hyperframes-pipeline", help="Render + post-process in one step")
    hyperframes_pipeline_p.add_argument("project_path", help="Path to Hyperframes project")
    hyperframes_pipeline_p.add_argument("--post-process", required=True, help="Post-processing operations as JSON list")
    hyperframes_pipeline_p.add_argument("-o", "--output", help="Final output file path")
