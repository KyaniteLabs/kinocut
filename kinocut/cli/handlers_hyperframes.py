"""CLI handlers for Hyperframes commands."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg, _with_spinner
from .formatting import (
    _format_hyperframes_add_block,
    _format_hyperframes_compositions,
    _format_hyperframes_init,
    _format_hyperframes_pipeline,
    _format_hyperframes_preview,
    _format_hyperframes_render,
    _format_hyperframes_still,
    _format_hyperframes_validate,
)
from .runner import CommandRunner, _out


def handle_hyperframes_commands(args: Any, *, use_json: bool) -> bool:
    """Handle Hyperframes commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _variables(a: Any, json_mode: bool) -> Any | None:
        value = getattr(a, "variables", None)
        if value is None:
            return None
        return _parse_json_arg(value, "variables", json_mode)

    def _render(a, j):
        from ..hyperframes_engine import render

        r = _with_spinner(
            f"Rendering {a.project_path}...",
            render,
            a.project_path,
            output_path=a.output,
            fps=a.fps,
            width=a.width,
            height=a.height,
            composition=getattr(a, "composition", None),
            quality=a.quality,
            format=a.output_format,
            resolution=getattr(a, "resolution", None),
            workers=a.workers,
            crf=a.crf,
            variables=_variables(a, j),
            variables_file=getattr(a, "variables_file", None),
        )
        _out(r, j, lambda res: _format_hyperframes_render(res, a.project_path))

    runner.register("hyperframes-render", _render)

    def _compositions(a, j):
        from ..hyperframes_engine import compositions

        r = _with_spinner("Listing compositions...", compositions, a.project_path)
        _out(
            r,
            j,
            lambda res: _format_hyperframes_compositions(res, a.project_path),
            json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r,
        )

    runner.register("hyperframes-compositions", _compositions)

    def _preview(a, j):
        from ..hyperframes_engine import preview

        r = _with_spinner("Launching Hyperframes preview...", preview, a.project_path, port=a.port)
        _out(
            r,
            j,
            _format_hyperframes_preview,
            json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r,
        )

    runner.register("hyperframes-preview", _preview)

    def _still(a, j):
        from ..hyperframes_engine import still

        r = _with_spinner(
            f"Rendering still frame {a.frame}...",
            still,
            a.project_path,
            output_path=a.output,
            frame=a.frame,
            variables=_variables(a, j),
            variables_file=getattr(a, "variables_file", None),
        )
        _out(r, j, lambda res: _format_hyperframes_still(res, a.project_path))

    runner.register("hyperframes-still", _still)

    def _snapshot(a, j):
        from ..hyperframes_engine import snapshot

        r = _with_spinner(
            "Capturing Hyperframes snapshots...",
            snapshot,
            a.project_path,
            frames=a.frames,
            at=a.at,
            variables=_variables(a, j),
            variables_file=getattr(a, "variables_file", None),
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-snapshot", _snapshot)

    def _inspect(a, j):
        from ..hyperframes_engine import inspect

        r = _with_spinner(
            "Inspecting Hyperframes layout...", inspect, a.project_path, samples=a.samples, strict=a.strict
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-inspect", _inspect)

    def _info(a, j):
        from ..hyperframes_engine import info

        r = _with_spinner("Reading Hyperframes project info...", info, a.project_path)
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-info", _info)

    def _catalog(a, j):
        from ..hyperframes_engine import catalog

        r = _with_spinner("Reading Hyperframes catalog...", catalog, item_type=a.item_type, tag=a.tag)
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-catalog", _catalog)

    def _capture(a, j):
        from ..hyperframes_engine import capture

        r = _with_spinner("Capturing website...", capture, a.url, output=a.output, skip_assets=a.skip_assets)
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-capture", _capture)

    def _tts(a, j):
        from ..hyperframes_engine import tts

        r = _with_spinner(
            "Generating speech...", tts, a.text_or_file, output_path=a.output, voice=a.voice, speed=a.speed
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-tts", _tts)

    def _transcribe(a, j):
        from ..hyperframes_engine import transcribe

        r = _with_spinner(
            "Transcribing media...",
            transcribe,
            a.input_path,
            project_path=a.project_path,
            model=getattr(a, "model", None),
            language=getattr(a, "language", None),
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-transcribe", _transcribe)

    def _remove_background(a, j):
        from ..hyperframes_engine import remove_background

        r = _with_spinner(
            "Removing background...",
            remove_background,
            a.input_path,
            output_path=a.output,
            background_output_path=a.background_output,
            device=a.device,
            quality=a.quality,
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-remove-background", _remove_background)

    def _doctor(a, j):
        from ..hyperframes_engine import doctor

        r = _with_spinner("Checking Hyperframes environment...", doctor)
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-doctor", _doctor)

    def _benchmark(a, j):
        from ..hyperframes_engine import benchmark

        r = _with_spinner(
            "Benchmarking Hyperframes render...",
            benchmark,
            a.project_path,
            output_path=a.output,
            runs=getattr(a, "runs", None),
        )
        _out(r, j, print, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("hyperframes-benchmark", _benchmark)

    def _init(a, j):
        from ..hyperframes_engine import create_project

        r = _with_spinner(
            f"Creating project '{a.name}'...",
            create_project,
            a.name,
            output_dir=a.output_dir,
            template=a.template,
            video=getattr(a, "video", None),
            audio=getattr(a, "audio", None),
            skip_transcribe=getattr(a, "skip_transcribe", False),
            model=getattr(a, "model", None),
            language=getattr(a, "language", None),
            tailwind=getattr(a, "tailwind", False),
            resolution=getattr(a, "resolution", None),
        )
        _out(r, j, _format_hyperframes_init)

    runner.register("hyperframes-init", _init)

    def _add_block(a, j):
        from ..hyperframes_engine import add_block

        r = _with_spinner(
            f"Adding block '{a.block_name}'...",
            add_block,
            a.project_path,
            a.block_name,
            no_clipboard=getattr(a, "no_clipboard", False),
        )
        _out(r, j, _format_hyperframes_add_block)

    runner.register("hyperframes-add-block", _add_block)

    def _validate(a, j):
        from ..hyperframes_engine import validate

        r = _with_spinner("Validating project...", validate, a.project_path)
        _out(r, j, _format_hyperframes_validate)

    runner.register("hyperframes-validate", _validate)

    def _pipeline(a, j):
        from ..hyperframes_engine import render_and_post

        post_process = _parse_json_arg(a.post_process, "post-process", json_mode=j)
        r = _with_spinner(
            f"Running pipeline for {a.project_path}...",
            render_and_post,
            a.project_path,
            post_process=post_process,
            output_path=a.output,
        )
        _out(r, j, lambda res: _format_hyperframes_pipeline(res, a.project_path))

    runner.register("hyperframes-pipeline", _pipeline)

    return runner.dispatch()
