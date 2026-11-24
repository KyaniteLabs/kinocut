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
    runner = CommandRunner(args, use_json)
    _register_diagnostics_commands(runner)
    _register_frame_commands(runner)
    _register_text_commands(runner)
    _register_audio_commands(runner)
    _register_transform_commands(runner)
    _register_render_commands(runner)
    _register_edit_command(runner)
    return runner.dispatch()


def _format_doctor_with_readiness(report: dict) -> None:
    from rich.markup import escape
    from rich.table import Table

    from .formatting import console

    _format_doctor_text(report)
    offline = next((check["details"] for check in report["checks"] if check["name"] == "offline_readiness"), None)
    if offline:
        table = Table(title=f"Offline Readiness (mode {'on' if offline['enabled'] else 'off'})")
        for label in ("Feature", "Status", "Local model"):
            table.add_column(label)
        for feature, details in offline["features"].items():
            table.add_row(feature, "Ready" if details["ready"] else "Not ready", escape(details["model"] or "-"))
        console.print(table)


def _register_diagnostics_commands(runner: CommandRunner) -> None:
    def _doctor(a, j):
        from ..doctor import run_diagnostics

        _out(run_diagnostics(), j or a.json, _format_doctor_with_readiness)

    runner.register("doctor", _doctor)
    _info_default = plain_cmd(
        "kinocut.engine_probe:probe",
        "input",
        formatter=_format_info_text,
        json_transform=lambda r: {
            "success": True,
            "data": r.model_dump() if hasattr(r, "model_dump") else r,
        },
    )
    _info_exact = plain_cmd(
        "kinocut.engine_probe:probe_exact",
        "input",
        formatter=_format_info_text,
        json_transform=lambda r: {
            "success": True,
            "data": r.model_dump() if hasattr(r, "model_dump") else r,
        },
    )

    def _info(a, j):
        (_info_exact if getattr(a, "exact", False) else _info_default)(a, j)

    runner.register("info", _info)


def _register_frame_commands(runner: CommandRunner) -> None:
    runner.register(
        "extract-frame",
        engine_cmd(
            "kinocut.engine_thumbnail:thumbnail",
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
            "kinocut.engine_edit:trim",
            "Trimming...",
            "input",
            formatter=_format_edit_text,
            start="start",
            duration="duration",
            end="end",
            output_path="output",
            accurate="accurate",
        ),
    )
    runner.register(
        "merge",
        engine_cmd(
            "kinocut.engine_merge:merge",
            "Merging...",
            "inputs",
            formatter=_format_edit_text,
            output_path="output",
            transition="transition",
            transitions="transitions",
            transition_duration="transition_duration",
        ),
    )
    runner.register(
        "thumbnail",
        plain_cmd(
            "kinocut.engine_thumbnail:thumbnail",
            "input",
            formatter=_format_edit_text,
            timestamp="timestamp",
            output_path="output",
        ),
    )
    runner.register(
        "preview",
        engine_cmd(
            "kinocut.engine_preview:preview",
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
            "kinocut.engine_storyboard:storyboard",
            "Extracting storyboard...",
            "input",
            formatter=_format_storyboard_text,
            output_dir="output_dir",
            frame_count="frames",
        ),
    )


def _register_text_commands(runner: CommandRunner) -> None:
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
            "kinocut.engine_watermark:watermark",
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


def _register_audio_commands(runner: CommandRunner) -> None:
    runner.register(
        "add-audio",
        engine_cmd(
            "kinocut.engine_audio_ops:add_audio",
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
            duration_policy="duration_policy",
        ),
    )
    runner.register(
        "extract-audio",
        engine_cmd(
            "kinocut.engine_extract_audio:extract_audio",
            "Extracting audio...",
            "input",
            formatter=_format_extract_audio_text,
            output_path="output",
            format="audio_format",
            json_transform=lambda r: {"success": True, "output_path": r},
        ),
    )


def _register_transform_commands(runner: CommandRunner) -> None:
    runner.register(
        "resize",
        engine_cmd(
            "kinocut.engine_resize:resize",
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
            "kinocut.engine_speed:speed",
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
            "kinocut.engine_convert:convert",
            "Converting...",
            "input",
            formatter=_format_edit_text,
            format="fmt",
            quality="quality",
            output_path="output",
            two_pass="two_pass",  # noqa: S106 - namespace attribute mapping, not a credential
            target_bitrate="target_bitrate",
        ),
    )
    runner.register(
        "crop",
        engine_cmd(
            "kinocut.engine_crop:crop",
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
            "kinocut.engine_rotate:rotate",
            "Rotating...",
            "input",
            formatter=_format_edit_text,
            angle="angle",
            flip_horizontal="flip_h",
            flip_vertical="flip_v",
            output_path="output",
        ),
    )


def _register_render_commands(runner: CommandRunner) -> None:
    runner.register(
        "fade",
        engine_cmd(
            "kinocut.engine_fade:fade",
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
            "kinocut.engine_export:export_video",
            "Exporting...",
            "input",
            formatter=_format_edit_text,
            quality="quality",
            format="fmt",
            output_path="output",
            c2pa_manifest_path="c2pa_manifest",
            c2pa_tool_path="c2pa_tool",
            c2pa_signer_path="c2pa_signer_path",
        ),
    )


def _register_edit_command(runner: CommandRunner) -> None:
    from ..engine import edit_timeline as _edit_timeline
    from ..models import Timeline

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
