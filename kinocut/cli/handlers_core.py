"""Core CLI command handlers."""

from __future__ import annotations

import json as _json
from typing import Any

from .common import _parse_json_arg, _with_spinner
from .formatting import (
    _format_doctor_text,
    _format_edit_text,
    _format_extract_audio_text,
    _format_info_text,
    _format_storyboard_text,
    _format_thumbnail_text,
)
from .runner import CommandRunner, _out, engine_cmd, plain_cmd


def handle_initial_command(args: Any, *, use_json: bool) -> bool:
    from ..engine import edit_timeline as _edit_timeline
    from ..models import Timeline

    runner = CommandRunner(args, use_json)

    def _doctor(a, j):
        from ..doctor import run_diagnostics

        _out(run_diagnostics(), j or a.json, _format_doctor_text)

    runner.register("doctor", _doctor)
    runner.register(
        "info",
        plain_cmd(
            "mcp_video.engine:probe",
            "input",
            formatter=_format_info_text,
            json_transform=lambda r: {
                "success": True,
                "data": r.model_dump() if hasattr(r, "model_dump") else r,
            },
        ),
    )
    runner.register(
        "extract-frame",
        engine_cmd(
            "mcp_video.engine:thumbnail",
            "Extracting frame...",
            "input",
            formatter=_format_thumbnail_text,
            timestamp="timestamp",
            output_path="output",
            json_transform=lambda r: {
                "success": True,
                **(r.model_dump() if hasattr(r, "model_dump") else r),
            },
        ),
    )
    runner.register(
        "trim",
        engine_cmd(
            "mcp_video.engine:trim",
            "Trimming...",
            "input",
            formatter=_format_edit_text,
            start="start",
            duration="duration",
            end="end",
            output_path="output",
        ),
    )
    runner.register(
        "merge",
        engine_cmd(
            "mcp_video.engine:merge",
            "Merging...",
            "inputs",
            formatter=_format_edit_text,
            output_path="output",
            transition="transition",
            transitions="transitions",
            transition_duration="transition_duration",
        ),
    )

    def _add_text(a, j):
        from ..engine import add_text

        _out(
            _with_spinner(
                "Adding text...",
                add_text,
                a.input,
                text=a.text,
                position=a.position,
                font=a.font,
                size=a.size,
                color=a.color,
                shadow=not a.no_shadow,
                start_time=a.start_time,
                duration=a.duration,
                output_path=a.output,
            ),
            j,
            _format_edit_text,
        )

    runner.register("add-text", _add_text)
    runner.register(
        "add-audio",
        engine_cmd(
            "mcp_video.engine:add_audio",
            "Adding audio...",
            "video",
            "audio",
            formatter=_format_edit_text,
            volume="volume",
            fade_in="fade_in",
            fade_out="fade_out",
            mix="mix",
            start_time="start_time",
            output_path="output",
        ),
    )
    runner.register(
        "resize",
        engine_cmd(
            "mcp_video.engine:resize",
            "Resizing...",
            "input",
            formatter=_format_edit_text,
            width="width",
            height="height",
            aspect_ratio="aspect_ratio",
            quality="quality",
            output_path="output",
        ),
    )
    runner.register(
        "speed",
        engine_cmd(
            "mcp_video.engine:speed",
            "Changing speed...",
            "input",
            formatter=_format_edit_text,
            factor="factor",
            output_path="output",
        ),
    )
    runner.register(
        "convert",
        engine_cmd(
            "mcp_video.engine:convert",
            "Converting...",
            "input",
            formatter=_format_edit_text,
            format="fmt",
            quality="quality",
            output_path="output",
        ),
    )
    runner.register(
        "thumbnail",
        plain_cmd(
            "mcp_video.engine:thumbnail",
            "input",
            formatter=_format_edit_text,
            timestamp="timestamp",
            output_path="output",
        ),
    )
    runner.register(
        "preview",
        engine_cmd(
            "mcp_video.engine:preview",
            "Generating preview...",
            "input",
            formatter=_format_edit_text,
            output_path="output",
            scale_factor="scale",
        ),
    )
    runner.register(
        "storyboard",
        engine_cmd(
            "mcp_video.engine:storyboard",
            "Extracting storyboard...",
            "input",
            formatter=_format_storyboard_text,
            output_dir="output_dir",
            frame_count="frames",
        ),
    )

    def _subs(a, j):
        from ..engine import subtitles

        kwargs = {"subtitle_path": a.subtitle, "output_path": a.output}
        if a.style is not None:
            kwargs["style"] = a.style
        _out(
            _with_spinner("Burning subtitles...", subtitles, a.input, **kwargs),
            j,
            _format_edit_text,
        )

    runner.register("subtitles", _subs)
    runner.register(
        "watermark",
        engine_cmd(
            "mcp_video.engine:watermark",
            "Adding watermark...",
            "input",
            formatter=_format_edit_text,
            image_path="image",
            position="position",
            opacity="opacity",
            margin="margin",
            output_path="output",
            crf="crf",
            preset="preset",
        ),
    )
    runner.register(
        "crop",
        engine_cmd(
            "mcp_video.engine:crop",
            "Cropping...",
            "input",
            formatter=_format_edit_text,
            width="width",
            height="height",
            x="x",
            y="y",
            output_path="output",
        ),
    )
    runner.register(
        "rotate",
        engine_cmd(
            "mcp_video.engine:rotate",
            "Rotating...",
            "input",
            formatter=_format_edit_text,
            angle="angle",
            flip_horizontal="flip_h",
            flip_vertical="flip_v",
            output_path="output",
        ),
    )
    runner.register(
        "fade",
        engine_cmd(
            "mcp_video.engine:fade",
            "Applying fade...",
            "input",
            formatter=_format_edit_text,
            fade_in="fade_in",
            fade_out="fade_out",
            output_path="output",
            crf="crf",
            preset="preset",
        ),
    )
    runner.register(
        "export",
        engine_cmd(
            "mcp_video.engine:export_video",
            "Exporting...",
            "input",
            formatter=_format_edit_text,
            quality="quality",
            format="fmt",
            output_path="output",
        ),
    )
    runner.register(
        "extract-audio",
        engine_cmd(
            "mcp_video.engine:extract_audio",
            "Extracting audio...",
            "input",
            formatter=_format_extract_audio_text,
            output_path="output",
            format="audio_format",
            json_transform=lambda r: {"success": True, "output_path": r},
        ),
    )

    def _edit(a, j):
        timeline_arg = a.timeline.strip()
        if timeline_arg.startswith(("{", "[")):
            tl = Timeline.model_validate(_parse_json_arg(timeline_arg, "timeline", json_mode=j))
        else:
            with open(timeline_arg) as f:
                tl = Timeline.model_validate(_json.load(f))
        _out(
            _with_spinner("Editing timeline...", _edit_timeline, tl, output_path=a.output),
            j,
            _format_edit_text,
        )

    runner.register("edit", _edit)
    return runner.dispatch()
