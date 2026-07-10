"""CLI handlers for media processing commands."""

from __future__ import annotations

import json as _json
from typing import Any

from .common import _parse_json_arg, _with_spinner
from .formatting import (
    _format_audio_waveform,
    _format_batch_text,
    _format_compare_quality,
    _format_detect_scenes,
    _format_edit_text,
    _format_export_frames,
    _format_generate_subtitles,
    _format_read_metadata,
    _format_templates,
    console,
)
from .runner import CommandRunner, _out, engine_cmd, plain_cmd


def handle_media_commands(args: Any, *, use_json: bool) -> bool:
    from ..engine import (
        apply_filter,
        compare_quality,
        export_frames,
        generate_subtitles,
        normalize_audio,
        video_batch,
        write_metadata,
    )

    runner = CommandRunner(args, use_json)

    def _filter(a, j):
        _out(
            _with_spinner(
                "Applying filter...",
                apply_filter,
                a.input,
                filter_type=a.filter_type,
                params=_parse_json_arg(a.params, "params", json_mode=j) if a.params else {},
                output_path=a.output,
                crf=a.crf,
                preset=a.preset,
            ),
            j,
            _format_edit_text,
        )

    runner.register("filter", _filter)

    def _blur(a, j):
        _out(
            _with_spinner(
                "Applying blur...",
                apply_filter,
                a.input,
                filter_type="blur",
                params={"radius": a.radius, "strength": a.strength},
                output_path=a.output,
            ),
            j,
            _format_edit_text,
        )

    runner.register("blur", _blur)
    runner.register(
        "reverse",
        engine_cmd(
            "mcp_video.engine:reverse", "Reversing...", "input", formatter=_format_edit_text, output_path="output"
        ),
    )
    runner.register(
        "chroma-key",
        engine_cmd(
            "mcp_video.engine:chroma_key",
            "Removing green screen...",
            "input",
            formatter=_format_edit_text,
            color="color",
            similarity="similarity",
            blend="blend",
            output_path="output",
        ),
    )

    def _color_grade(a, j):
        _out(
            _with_spinner(
                "Applying color grade...",
                apply_filter,
                a.input,
                filter_type="color_preset",
                params={"preset": a.preset},
                output_path=a.output,
            ),
            j,
            _format_edit_text,
        )

    runner.register("color-grade", _color_grade)

    def _normalize(a, j):
        _out(
            _with_spinner(
                "Normalizing audio...",
                normalize_audio,
                a.input,
                target_lufs=a.lufs,
                output_path=a.output,
                **({"lra": a.lra} if a.lra is not None else {}),
            ),
            j,
            _format_edit_text,
        )

    runner.register("normalize-audio", _normalize)
    runner.register(
        "overlay-video",
        engine_cmd(
            "mcp_video.engine:overlay_video",
            "Compositing overlay...",
            "background",
            formatter=_format_edit_text,
            overlay_path="overlay",
            position="position",
            width="width",
            height="height",
            opacity="opacity",
            start_time="start_time",
            duration="duration",
            output_path="output",
            crf="crf",
            preset="preset",
        ),
    )
    runner.register(
        "split-screen",
        engine_cmd(
            "mcp_video.engine:split_screen",
            "Creating split screen...",
            "left",
            formatter=_format_edit_text,
            right_path="right",
            layout="layout",
            output_path="output",
        ),
    )

    def _batch(a, j):
        _out(
            video_batch(
                a.inputs,
                operation=a.operation,
                params=_parse_json_arg(a.params, "params", json_mode=j) if a.params else {},
                output_dir=a.output_dir,
            ),
            j,
            _format_batch_text,
        )

    runner.register("batch", _batch)
    runner.register(
        "detect-scenes",
        engine_cmd(
            "mcp_video.engine:detect_scenes",
            "Detecting scenes...",
            "input",
            formatter=_format_detect_scenes,
            threshold="threshold",
            min_scene_duration="min_duration",
        ),
    )
    runner.register(
        "create-from-images",
        engine_cmd(
            "mcp_video.engine:create_from_images",
            "Creating video from images...",
            "inputs",
            formatter=_format_edit_text,
            output_path="output",
            fps="fps",
        ),
    )

    def _export_frames(a, j):
        _out(
            _with_spinner(
                "Exporting frames...",
                export_frames,
                a.input,
                output_dir=a.output_dir,
                fps=a.fps,
                format="mjpeg" if a.image_format == "jpg" else a.image_format,
            ),
            j,
            lambda res: _format_export_frames(res, a.image_format),
        )

    runner.register("export-frames", _export_frames)

    def _compare(a, j):
        _out(
            _with_spinner(
                "Comparing quality...",
                compare_quality,
                a.original,
                a.distorted,
                metrics=a.metrics if a.metrics else None,
            ),
            j,
            _format_compare_quality,
        )

    runner.register("compare-quality", _compare)
    runner.register(
        "read-metadata", plain_cmd("mcp_video.engine:read_metadata", "input", formatter=_format_read_metadata)
    )

    def _write_meta(a, j):
        try:
            tags = _json.loads(a.tags)
        except _json.JSONDecodeError as e:
            console.print(f"[bold red]Invalid JSON in --tags: {e}[/bold red]")
            raise SystemExit(1) from None
        _out(
            _with_spinner("Writing metadata...", write_metadata, a.input, metadata=tags, output_path=a.output),
            j,
            _format_edit_text,
        )

    runner.register("write-metadata", _write_meta)
    runner.register(
        "stabilize",
        engine_cmd(
            "mcp_video.engine:stabilize",
            "Stabilizing...",
            "input",
            formatter=_format_edit_text,
            smoothing="smoothing",
            zooming="zooming",
            output_path="output",
        ),
    )
    runner.register(
        "apply-mask",
        engine_cmd(
            "mcp_video.engine:apply_mask",
            "Applying mask...",
            "input",
            formatter=_format_edit_text,
            mask_path="mask",
            feather="feather",
            output_path="output",
        ),
    )
    runner.register(
        "audio-waveform",
        engine_cmd(
            "mcp_video.engine:audio_waveform",
            "Extracting waveform...",
            "input",
            formatter=_format_audio_waveform,
            bins="bins",
        ),
    )

    def _gen_subs(a, j):
        _out(
            _with_spinner(
                "Generating subtitles...",
                generate_subtitles,
                _parse_json_arg(a.entries, "entries", json_mode=j),
                a.input,
                burn=a.burn,
                output_path=a.output,
            ),
            j,
            _format_generate_subtitles,
        )

    runner.register("generate-subtitles", _gen_subs)

    def _templates(a, j):
        from ..templates import TEMPLATES

        _out(
            {
                "success": True,
                "templates": {
                    name: {
                        "tiktok": "TikTok (9:16, 1080x1920) — vertical video with optional caption and music",
                        "youtube-shorts": "YouTube Shorts (9:16) — title at top, vertical video",
                        "instagram-reel": "Instagram Reel (9:16) — caption at bottom, vertical video",
                        "youtube": "YouTube (16:9, 1920x1080) — horizontal video with title card and outro",
                        "instagram-post": "Instagram Post (1:1, 1080x1080) — square video with caption",
                    }.get(name, "")
                    for name in TEMPLATES
                },
            },
            j,
            _format_templates,
        )

    runner.register("templates", _templates)

    def _template(a, j):
        from ..engine import edit_timeline
        from ..templates import TEMPLATES

        kwargs = {"video_path": a.input, "output_path": a.output}
        for attr, key in [(a.caption, "caption"), (a.title, "title"), (a.music, "music_path"), (a.outro, "outro_path")]:
            if attr:
                kwargs[key] = attr
        _out(
            _with_spinner(
                f"Applying {a.name} template...", edit_timeline, TEMPLATES[a.name](**kwargs), output_path=a.output
            ),
            j,
            _format_edit_text,
        )

    runner.register("template", _template)

    def _repurpose_plan(a, j):
        from ..engine_repurpose import repurpose_plan

        _out(
            repurpose_plan(a.input, output_dir=a.output_dir, platforms=a.platforms),
            j,
            print,
        )

    runner.register("repurpose-plan", _repurpose_plan)

    def _repurpose(a, j):
        from ..engine_repurpose import repurpose

        _out(
            _with_spinner(
                "Rendering repurposing package...",
                repurpose,
                a.input,
                output_dir=a.output_dir,
                platforms=a.platforms,
                include_release_checkpoint=not a.skip_release_checkpoint,
                min_score=a.min_score,
            ),
            j,
            print,
        )

    runner.register("repurpose", _repurpose)
    return runner.dispatch()
