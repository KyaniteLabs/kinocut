"""Rich output formatting helpers for the mcp-video CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)

console = Console()
err_console = Console(stderr=True)


def _model_dump(result: Any) -> Any:
    return result.model_dump() if hasattr(result, "model_dump") else result


def _format_success_panel(
    content: str | list[str],
    title: str = "Done",
    border_style: str = "green",
) -> None:
    """Print a success Panel with consistent styling."""
    text = "\n".join(content) if isinstance(content, list) else content
    console.print(Panel(text, border_style=border_style, title=title))


def _format_path_panel(label: str, result: Any) -> None:
    path = _model_dump(result).get("output_path", result) if isinstance(_model_dump(result), dict) else result
    path_text = str(path)
    filename = Path(path_text).name
    _format_success_panel(
        [
            f"[bold green]{label}:[/bold green] {filename}",
            f"[bold green]Output:[/bold green] {path_text}",
        ]
    )


def _format_composite_layers_text(result: Any) -> None:
    """Display composite-layers result without implying dry-runs rendered media."""
    data = _model_dump(result)
    if data.get("dry_run"):
        lines = [
            f"[bold green]Operation:[/bold green] {data.get('operation', 'composite_layers_dry_run')}",
            f"[bold green]Planned output:[/bold green] {data.get('output_path', 'N/A')}",
        ]
        if data.get("layer_plan_path"):
            lines.append(f"[bold green]Layer plan:[/bold green] {data['layer_plan_path']}")
        lines.append("[bold yellow]No media rendered.[/bold yellow]")
        _format_success_panel(lines, title="Composite Layers Plan", border_style="yellow")
        return
    _format_path_panel("Composite layers", result)


def _format_workflow_validation(result: Any) -> None:
    """Display a workflow-validation verdict as a success panel."""
    data = result if isinstance(result, dict) else _model_dump(result)
    ops = data.get("ops", [])
    lines = [
        f"[bold green]Workflow:[/bold green] {escape(str(data.get('name') or '(unnamed)'))}",
        f"[bold green]Valid:[/bold green] {data.get('valid')}",
        f"[bold green]Steps:[/bold green] {len(data.get('steps', []))}",
        f"[bold green]Ops:[/bold green] {escape(', '.join(ops)) if ops else '(none)'}",
    ]
    _format_success_panel(lines, title="Workflow Validation", border_style="green")


def _format_workflow_plan(result: Any) -> None:
    """Display a workflow plan artifact as a success panel (no media rendered)."""
    data = result if isinstance(result, dict) else _model_dump(result)
    workflow = data.get("workflow") or {}
    ops = [step.get("op") for step in data.get("steps", [])]
    warnings = data.get("warnings", [])
    lines = [
        f"[bold green]Workflow:[/bold green] {escape(str(workflow.get('name') or '(unnamed)'))}",
        f"[bold green]Steps:[/bold green] {len(data.get('steps', []))}",
        f"[bold green]Ops:[/bold green] {escape(', '.join(o for o in ops if o)) if ops else '(none)'}",
        f"[bold green]Sources:[/bold green] {len(data.get('sources', []))}",
        f"[bold green]Outputs:[/bold green] {len(data.get('outputs', []))}",
        f"[bold green]Variants:[/bold green] {len(data.get('variants', []))}",
    ]
    if warnings:
        lines.append(f"[yellow]Warnings ({len(warnings)}):[/yellow]")
        for warning in warnings[:5]:
            lines.append(f"  - {escape(str(warning.get('message', warning)))}")
    lines.append("[bold yellow]No media rendered.[/bold yellow]")
    _format_success_panel(lines, title="Workflow Plan", border_style="yellow")


def _format_workflow_render(result: Any) -> None:
    """Display a workflow render receipt (or an all-variants batch) as a panel."""
    data = result if isinstance(result, dict) else _model_dump(result)
    if data.get("receipt_kind") == "workflow_batch":
        _format_workflow_batch(data)
        return
    workflow = data.get("workflow") or {}
    steps = data.get("steps", [])
    completed = sum(1 for step in steps if step.get("status") == "completed")
    outputs = data.get("outputs", [])
    cleanup = data.get("cleanup_manifest") or {}
    lines = [
        f"[bold green]Workflow:[/bold green] {escape(str(workflow.get('name') or '(unnamed)'))}",
    ]
    if workflow.get("variant"):
        lines.append(f"[bold green]Variant:[/bold green] {escape(str(workflow['variant']))}")
    lines.extend(
        [
            f"[bold green]Status:[/bold green] {escape(str(data.get('status')))}",
            f"[bold green]Steps:[/bold green] {completed}/{len(steps)} completed",
            f"[bold green]Outputs:[/bold green] {escape(', '.join(o.get('path', '') for o in outputs)) or '(none)'}",
            f"[bold green]Intermediates cleaned:[/bold green] {cleanup.get('cleaned')}",
        ]
    )
    _format_success_panel(lines, title="Workflow Render", border_style="green")


def _format_workflow_batch(data: dict) -> None:
    """Display an all-variants batch render summary as a success panel."""
    workflow = data.get("workflow") or {}
    variants = data.get("variants", [])
    lines = [
        f"[bold green]Workflow:[/bold green] {escape(str(workflow.get('name') or '(unnamed)'))}",
        f"[bold green]Status:[/bold green] {escape(str(data.get('status')))}",
        f"[bold green]Variants:[/bold green] {data.get('count', len(variants))} rendered",
    ]
    for receipt in variants:
        variant_name = (receipt.get("workflow") or {}).get("variant")
        paths = ", ".join(o.get("path", "") for o in receipt.get("outputs", []))
        lines.append(f"  - [cyan]{escape(str(variant_name))}[/cyan]: {escape(paths) or '(no outputs)'}")
    _format_success_panel(lines, title="Workflow Render (all variants)", border_style="green")


def _format_workflow_inspect(result: Any) -> None:
    """Display a normalized receipt inspection as a success panel."""
    data = result if isinstance(result, dict) else _model_dump(result)
    status = data.get("status") or {}
    summary = (data.get("integrity") or {}).get("summary") or {}
    review = data.get("human_review") or []
    lines = [
        f"[bold green]Kind:[/bold green] {escape(str(data.get('kind')))}",
        f"[bold green]Tool:[/bold green] {escape(str(data.get('tool')))}",
        f"[bold green]Schema version:[/bold green] {data.get('schema_version')}",
        f"[bold green]Status:[/bold green] {escape(str(status.get('overall')))}",
        f"[bold green]Outputs:[/bold green] {len(data.get('outputs', []))}",
        f"[bold green]Integrity:[/bold green] {summary.get('matched', 0)}/{summary.get('checked', 0)} match"
        f" ({summary.get('mismatched', 0)} mismatched, {summary.get('missing', 0)} missing)",
    ]
    if status.get("failed_step"):
        lines.append(f"[bold red]Failed step:[/bold red] {escape(str(status['failed_step']))}")
    if review:
        lines.append(f"[yellow]Human review ({len(review)}):[/yellow]")
        for note in review[:5]:
            lines.append(f"  - {escape(str(note))}")
    border = "yellow" if (review or summary.get("mismatched") or summary.get("missing")) else "green"
    _format_success_panel(lines, title="Workflow Inspect", border_style=border)


def _format_info_text(info: Any) -> None:
    """Display video info as a rich table."""
    table = Table(title="Video Info", show_header=False, border_style="blue")
    table.add_column("Property", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Path", str(getattr(info, "path", "N/A")))
    table.add_row("Duration", f"{getattr(info, 'duration', 0):.2f}s")
    table.add_row("Resolution", getattr(info, "resolution", "N/A"))
    table.add_row("Aspect Ratio", getattr(info, "aspect_ratio", "N/A"))
    table.add_row("FPS", str(getattr(info, "fps", "N/A")))
    table.add_row("Video Codec", getattr(info, "codec", "N/A"))
    table.add_row("Audio Codec", getattr(info, "audio_codec", "N/A"))
    table.add_row("Size", f"{getattr(info, 'size_mb', 0):.2f} MB")
    table.add_row("Format", getattr(info, "format", "N/A"))
    console.print(table)


def _format_edit_text(result: Any) -> None:
    """Display edit result as a success panel."""
    data = _model_dump(result)
    lines = [
        f"[bold green]Operation:[/bold green] {data.get('operation', 'N/A')}",
        f"[bold green]Output:[/bold green] {data.get('output_path', 'N/A')}",
    ]
    if data.get("duration") is not None:
        lines.append(f"[bold green]Duration:[/bold green] {data['duration']:.2f}s")
    if data.get("resolution"):
        lines.append(f"[bold green]Resolution:[/bold green] {data['resolution']}")
    if data.get("size_mb") is not None:
        lines.append(f"[bold green]Size:[/bold green] {data['size_mb']:.2f} MB")
    if data.get("format"):
        lines.append(f"[bold green]Format:[/bold green] {data['format']}")
    _format_success_panel(lines)


def _format_thumbnail_text(result: Any) -> None:
    """Display thumbnail/extract-frame result."""
    data = _model_dump(result)
    frame_path = data.get("frame_path", "N/A")
    timestamp = data.get("timestamp", 0.0)
    _format_success_panel(
        f"[bold green]Frame extracted:[/bold green] {frame_path}\n[bold green]Timestamp:[/bold green] {timestamp:.2f}s"
    )


def _format_storyboard_text(result: Any) -> None:
    """Display storyboard result."""
    data = _model_dump(result)
    frames = data.get("frames", [])
    grid = data.get("grid")
    lines = [
        f"[bold green]Frames:[/bold green] {data.get('count', len(frames))}",
    ]
    if frames:
        lines.append(f"[bold green]Output dir:[/bold green] {frames[0].rsplit('/', 1)[0] if '/' in frames[0] else '.'}")
    if grid:
        lines.append(f"[bold green]Grid:[/bold green] {grid}")
    _format_success_panel(lines, title="Storyboard")


def _format_batch_text(result: dict) -> None:
    """Display batch result as a table."""
    if result.get("success") is False:
        error_msg = result.get("error", {})
        msg = error_msg.get("message", str(error_msg)) if isinstance(error_msg, dict) else str(error_msg)
        console.print(f"[bold red]Batch failed: {msg}[/bold red]")
        return
    table = Table(title="Batch Results")
    table.add_column("File", style="cyan")
    table.add_column("Status")
    table.add_column("Output")
    for r in result.get("results", []):
        status = "[green]OK[/green]" if r.get("success") else f"[red]{r.get('error', 'Failed')}[/red]"
        table.add_row(r.get("input", "N/A"), status, r.get("output_path", "-"))
    console.print(table)
    summary = f"[bold]{result['succeeded']}/{result['total']} succeeded[/bold]"
    if result.get("failed"):
        summary += f", [red]{result['failed']} failed[/red]"
    console.print(summary)


def _format_extract_audio_text(result: Any) -> None:
    """Display extract-audio result."""
    _format_success_panel(f"[bold green]Audio extracted:[/bold green] {result}")


def _format_doctor_text(report: dict[str, Any]) -> None:
    """Display diagnostics as a compact table."""
    summary = report["summary"]
    status = "OK" if summary["required_ok"] else "Missing required dependencies"
    console.print(f"[bold]mcp-video doctor[/bold] — {status}")
    table = Table(title="Environment Checks")
    table.add_column("Name", style="cyan")
    table.add_column("Category")
    table.add_column("Required")
    table.add_column("Status")
    table.add_column("Version / Hint")
    for check in report["checks"]:
        state = "[green]OK[/green]" if check["ok"] else "[yellow]Missing[/yellow]"
        detail = check.get("version") or check.get("install_hint") or "-"
        table.add_row(check["name"], check["category"], "yes" if check["required"] else "no", state, escape(detail))
    console.print(table)


def _format_detect_scenes(result: Any) -> None:
    data = _model_dump(result)
    table = Table(title="Scene Detection")
    table.add_column("#", style="bold", justify="right")
    table.add_column("Start", style="cyan")
    table.add_column("End", style="cyan")
    table.add_column("Frames")
    for i, scene in enumerate(data.get("scenes", []), 1):
        table.add_row(
            str(i),
            f"{scene['start']:.2f}s",
            f"{scene['end']:.2f}s",
            f"{scene['start_frame']}-{scene['end_frame']}",
        )
    console.print(table)
    console.print(f"[bold]{data.get('scene_count', 0)} scenes detected[/bold] in {data.get('duration', 0):.2f}s")


def _format_export_frames(result: Any, image_format: str) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Frames:[/bold green] {data.get('frame_count', 0)}",
        f"[bold green]Format:[/bold green] {image_format}",
        f"[bold green]FPS:[/bold green] {data.get('fps', 0)}",
    ]
    if data.get("frame_paths"):
        lines.append(f"[bold green]Output dir:[/bold green] {data['frame_paths'][0].rsplit('/', 1)[0]}")
    _format_success_panel(lines, title="Frames Exported")


def _format_compare_quality(result: Any) -> None:
    data = _model_dump(result)
    table = Table(title="Quality Metrics")
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value")
    for k, v in data.get("metrics", {}).items():
        table.add_row(k.upper(), f"{v:.4f}")
    quality = data.get("overall_quality", "unknown")
    quality_style = {"high": "green", "medium": "yellow", "low": "red"}.get(quality, "white")
    table.add_row("Overall", f"[{quality_style}]{quality}[/{quality_style}]")
    console.print(table)


def _format_read_metadata(result: Any) -> None:
    data = _model_dump(result)
    table = Table(title="Metadata")
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    for field in ["title", "artist", "album", "comment", "date"]:
        val = data.get(field)
        if val:
            table.add_row(field.capitalize(), val)
    for k, v in data.get("tags", {}).items():
        table.add_row(k, str(v))
    if not data.get("title") and not data.get("tags"):
        console.print("[yellow]No metadata found.[/yellow]")
    else:
        console.print(table)


def _format_audio_waveform(result: Any) -> None:
    data = _model_dump(result)
    table = Table(title="Audio Waveform")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")
    table.add_row("Duration", f"{data.get('duration', 0):.2f}s")
    table.add_row("Mean Level", f"{data.get('mean_level', 0):.1f} dB")
    table.add_row("Max Level", f"{data.get('max_level', 0):.1f} dB")
    table.add_row("Min Level", f"{data.get('min_level', 0):.1f} dB")
    silence_count = len(data.get("silence_regions", []))
    table.add_row("Silence Regions", str(silence_count))
    console.print(table)


def _format_generate_subtitles(result: Any) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Entries:[/bold green] {data.get('entry_count', 0)}",
        f"[bold green]SRT Path:[/bold green] {data.get('srt_path', 'N/A')}",
    ]
    if data.get("video_path"):
        lines.append(f"[bold green]Video Path:[/bold green] {data['video_path']}")
    _format_success_panel(lines, title="Subtitles Generated")


def _format_templates(_result: Any = None) -> None:
    from ..templates import TEMPLATES

    descriptions = {
        "tiktok": "TikTok (9:16, 1080x1920) — vertical video with optional caption and music",
        "youtube-shorts": "YouTube Shorts (9:16) — title at top, vertical video",
        "instagram-reel": "Instagram Reel (9:16) — caption at bottom, vertical video",
        "youtube": "YouTube (16:9, 1920x1080) — horizontal video with title card and outro",
        "instagram-post": "Instagram Post (1:1, 1080x1080) — square video with caption",
    }
    table = Table(title="Available Templates")
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    for name in TEMPLATES:
        table.add_row(name, descriptions.get(name, ""))
    console.print(table)


def _format_auto_chapters(result: Any) -> None:
    table = Table(title="Auto Chapters")
    table.add_column("#", style="bold", justify="right")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Description")
    for i, chapter in enumerate(result, 1):
        if isinstance(chapter, (list, tuple)):
            ts, desc = chapter
        else:
            ts = chapter.get("timestamp", "")
            desc = chapter.get("description", "")
        table.add_row(str(i), f"{ts:.2f}s", desc)
    console.print(table)
    console.print(f"[bold]{len(result)} chapters detected[/bold]")


def _format_video_info_detailed(result: dict[str, Any]) -> None:
    table = Table(title="Detailed Video Info")
    table.add_column("Property", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Duration", f"{result.get('duration', 0):.2f}s")
    table.add_row("FPS", str(result.get("fps", "N/A")))
    table.add_row("Resolution", f"{result.get('resolution', 'N/A')}")
    table.add_row("Bitrate", f"{(result.get('bitrate') or 0) // 1000} kbps")
    table.add_row("Has Audio", str(result.get("has_audio", False)))
    table.add_row("Scene Changes", str(len(result.get("scene_changes", []))))
    for i, ts in enumerate(result.get("scene_changes", []), 1):
        table.add_row(f"  Scene {i}", f"{ts:.2f}s")
    console.print(table)


def _format_quality_check(result: Any) -> None:
    data = _model_dump(result)
    if not isinstance(data, dict):
        data = {}
    table = Table(title="Quality Check")
    table.add_column("Check", style="bold cyan")
    table.add_column("Status")
    table.add_column("Value")
    checks = data.get("checks", {})
    if isinstance(checks, dict):
        for check, info in checks.items():
            status = "[green]PASS[/green]" if info.get("passed") else "[red]FAIL[/red]"
            table.add_row(check, status, str(info.get("value", "")))
    elif isinstance(checks, list):
        for info in checks:
            if not isinstance(info, dict):
                continue
            status = "[green]PASS[/green]" if info.get("passed") else "[red]FAIL[/red]"
            score = info.get("score")
            message = info.get("message")
            value_parts = []
            if score is not None:
                try:
                    value_parts.append(f"{float(score):.1f}")
                except (TypeError, ValueError):
                    value_parts.append(escape(str(score)))
            if message:
                value_parts.append(escape(str(message)))
            table.add_row(str(info.get("name", "unknown")), status, " — ".join(value_parts))
    overall_passed = data.get("all_passed", data.get("passed", False))
    overall = "[green]PASS[/green]" if overall_passed else "[red]FAIL[/red]"
    console.print(table)
    console.print(f"[bold]Overall: {overall}[/bold]")


def _format_design_quality(result: Any) -> None:
    data = _model_dump(result)
    score = data.get("overall_score", "N/A")
    issues = data.get("issues", [])
    warnings = data.get("warnings", [])
    lines = [f"[bold green]Score:[/bold green] {score}"]
    if issues:
        lines.append(f"[red]Issues ({len(issues)}):[/red]")
        for issue in issues[:5]:
            lines.append(f"  - {issue}")
    if warnings:
        lines.append(f"[yellow]Warnings ({len(warnings)}):[/yellow]")
        for w in warnings[:5]:
            lines.append(f"  - {w}")
    _format_success_panel(lines, title="Design Quality")


def _format_fix_design_issues(result: str) -> None:
    _format_success_panel(f"[bold green]Design fixed:[/bold green] {result}")


def _format_ai_transcribe(result: Any, output: str | None) -> None:
    data: dict[str, Any] = result if isinstance(result, dict) else {"success": True}
    text = str(data.get("text", ""))
    srt = data.get("srt_path", output or "N/A")
    lines = [f"[bold green]SRT:[/bold green] {srt}"]
    if text:
        lines.append(f"[bold green]Preview:[/bold green] {text[:200]}...")
    _format_success_panel(lines, title="Transcription")


def _format_video_analyze(result: dict[str, Any], no_transcript: bool) -> None:
    meta = result.get("metadata", {})
    meta_lines = []
    if meta.get("duration"):
        meta_lines.append(f"[bold]Duration:[/bold] {meta['duration']:.2f}s")
    if meta.get("width") and meta.get("height"):
        meta_lines.append(f"[bold]Resolution:[/bold] {meta['width']}x{meta['height']}")
    if meta.get("fps"):
        meta_lines.append(f"[bold]FPS:[/bold] {meta['fps']:.2f}")
    if meta.get("codec"):
        meta_lines.append(f"[bold]Video codec:[/bold] {meta['codec']}")
    if meta.get("audio_codec"):
        meta_lines.append(f"[bold]Audio codec:[/bold] {meta['audio_codec']}")
    if meta.get("size_bytes"):
        meta_lines.append(f"[bold]Size:[/bold] {meta['size_bytes'] // 1024:,} KB")
    console.print(Panel("\n".join(meta_lines) or "No metadata", title="[cyan]Metadata[/cyan]", border_style="cyan"))

    transcript = result.get("transcript")
    if transcript:
        text = transcript.get("text", "")
        lang = transcript.get("language", "unknown")
        segs = len(transcript.get("segments", []))
        preview = text[:300] + ("..." if len(text) > 300 else "")
        t_lines = [
            f"[bold]Language:[/bold] {lang}",
            f"[bold]Segments:[/bold] {segs}",
            f"[bold]Preview:[/bold] {preview}",
        ]
        if transcript.get("srt_path"):
            t_lines.append(f"[bold]SRT:[/bold] {transcript['srt_path']}")
        if transcript.get("txt_path"):
            t_lines.append(f"[bold]TXT:[/bold] {transcript['txt_path']}")
        if transcript.get("md_path"):
            t_lines.append(f"[bold]Markdown:[/bold] {transcript['md_path']}")
        if transcript.get("json_path"):
            t_lines.append(f"[bold]JSON:[/bold] {transcript['json_path']}")
        console.print(Panel("\n".join(t_lines), title="[green]Transcript[/green]", border_style="green"))
    elif not no_transcript:
        console.print(
            Panel(
                "[yellow]Transcript unavailable (Whisper not installed?)[/yellow]",
                title="Transcript",
                border_style="yellow",
            )
        )

    scenes = result.get("scenes")
    if scenes is not None:
        table = Table(title="Scenes", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Start", justify="right")
        table.add_column("End", justify="right")
        for i, sc in enumerate(scenes[:20], 1):
            table.add_row(str(i), f"{sc.get('start', 0):.2f}s", f"{sc.get('end', 0):.2f}s")
        if len(scenes) > 20:
            table.add_row("...", f"+{len(scenes) - 20} more", "")
        console.print(table)

    chapters = result.get("chapters")
    if chapters:
        ch_lines = [f"[bold]{ch['title']}[/bold] @ {ch['timestamp']:.2f}s" for ch in chapters[:10]]
        console.print(Panel("\n".join(ch_lines), title="[blue]Chapters[/blue]", border_style="blue"))

    audio = result.get("audio")
    if audio:
        a_lines = [
            f"[bold]Mean level:[/bold] {audio.get('mean_level', 'N/A')} dBFS",
            f"[bold]Max level:[/bold] {audio.get('max_level', 'N/A')} dBFS",
            f"[bold]Silence regions:[/bold] {len(audio.get('silence_regions', []))}",
        ]
        console.print(Panel("\n".join(a_lines), title="[yellow]Audio[/yellow]", border_style="yellow"))

    quality = result.get("quality")
    if quality:
        score = quality.get("overall_score", "N/A")
        console.print(
            Panel(
                f"[bold]Overall score:[/bold] {score}/100",
                title="[magenta]Quality[/magenta]",
                border_style="magenta",
            )
        )

    errors = result.get("errors", [])
    if errors:
        err_lines = [f"[red]{e['section']}:[/red] {e['error']}" for e in errors]
        console.print(Panel("\n".join(err_lines), title="[red]Warnings / Errors[/red]", border_style="red"))


def _format_ai_upscale(result: str, scale: float) -> None:
    _format_success_panel(f"[bold green]Upscaled ({scale}x):[/bold green] {result}")


def _format_ai_stem_separation(result: Any) -> None:
    data = result if isinstance(result, dict) else {}
    lines = []
    if isinstance(data, dict):
        for stem, path in data.items():
            lines.append(f"[bold green]{stem}:[/bold green] {path}")
    if not lines:
        lines.append("[dim]No stems found[/dim]")
    _format_success_panel(lines, title="Stem Separation")


def _format_ai_scene_detect(result: Any) -> None:
    scenes = result if isinstance(result, list) else result.get("scenes", [])
    table = Table(title="AI Scene Detection")
    table.add_column("#", style="bold", justify="right")
    table.add_column("Start", style="cyan")
    table.add_column("End", style="cyan")
    table.add_column("Confidence")
    for i, scene in enumerate(scenes, 1):
        if isinstance(scene, dict):
            table.add_row(
                str(i),
                f"{scene.get('start', 0):.2f}s",
                f"{scene.get('end', 0):.2f}s",
                f"{scene.get('confidence', 0):.2f}",
            )
        else:
            table.add_row(str(i), str(scene))
    console.print(table)
    console.print(f"[bold]{len(scenes)} scenes detected[/bold]")


def _format_ai_color_grade(result: str, style: str) -> None:
    _format_success_panel(f"[bold green]Color graded ({style}):[/bold green] {result}")


def _format_ai_remove_silence(result: str) -> None:
    _format_success_panel(f"[bold green]Silence removed:[/bold green] {result}")


def _format_hyperframes_render(result: Any, project_path: str) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Project:[/bold green] {project_path}",
        f"[bold green]Output:[/bold green] {data.get('output_path', 'N/A')}",
    ]
    if data.get("resolution"):
        lines.append(f"[bold green]Resolution:[/bold green] {data['resolution']}")
    if data.get("codec"):
        lines.append(f"[bold green]Codec:[/bold green] {data['codec']}")
    if data.get("size_mb") is not None:
        lines.append(f"[bold green]Size:[/bold green] {data['size_mb']:.2f} MB")
    if data.get("render_time") is not None:
        lines.append(f"[bold green]Render time:[/bold green] {data['render_time']:.1f}s")
    _format_success_panel(lines, title="Hyperframes Render")


def _format_hyperframes_compositions(result: Any, project_path: str) -> None:
    data = _model_dump(result)
    table = Table(title=f"Compositions — {project_path}")
    table.add_column("ID", style="bold cyan")
    table.add_column("Width")
    table.add_column("Height")
    table.add_column("FPS")
    table.add_column("Frames")
    for comp in data.get("compositions", []):
        table.add_row(
            comp.get("id", ""),
            str(comp.get("width", "")),
            str(comp.get("height", "")),
            str(comp.get("fps", "")),
            str(comp.get("duration_in_frames", "")),
        )
    console.print(table)


def _format_hyperframes_preview(result: Any) -> None:
    data = _model_dump(result) if hasattr(result, "model_dump") else (result if isinstance(result, dict) else {})
    _format_success_panel(
        f"[bold green]Preview running:[/bold green] {data.get('url', 'N/A')}\n"
        f"[bold green]Port:[/bold green] {data.get('port', 'N/A')}\n"
        f"[bold green]Project:[/bold green] {data.get('project_path', 'N/A')}",
        title="Hyperframes Preview",
    )


def _format_hyperframes_still(result: Any, project_path: str) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Project:[/bold green] {project_path}",
        f"[bold green]Frame:[/bold green] {data.get('frame', 0)}",
        f"[bold green]Output:[/bold green] {data.get('output_path', 'N/A')}",
    ]
    if data.get("resolution"):
        lines.append(f"[bold green]Resolution:[/bold green] {data['resolution']}")
    _format_success_panel(lines, title="Hyperframes Still")


def _format_hyperframes_init(result: Any) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Project:[/bold green] {data.get('project_path', 'N/A')}",
        f"[bold green]Template:[/bold green] {data.get('template', 'N/A')}",
    ]
    if data.get("files"):
        lines.append(f"[bold green]Files created:[/bold green] {len(data['files'])}")
    _format_success_panel(lines, title="Hyperframes Project Created")


def _format_hyperframes_add_block(result: Any) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Project:[/bold green] {data.get('project_path', 'N/A')}",
        f"[bold green]Block:[/bold green] {data.get('block_name', 'N/A')}",
    ]
    if data.get("files_added"):
        lines.append(f"[bold green]Files added:[/bold green] {len(data['files_added'])}")
    _format_success_panel(lines, title="Hyperframes Block Added")


def _format_hyperframes_validate(result: Any) -> None:
    data = _model_dump(result)
    status = "[green]Valid[/green]" if data.get("valid") else "[red]Invalid[/red]"
    lines = [
        f"[bold green]Project:[/bold green] {data.get('project_path', 'N/A')}",
        f"[bold green]Status:[/bold green] {status}",
    ]
    if data.get("issues"):
        lines.append(f"[red]Issues ({len(data['issues'])}):[/red]")
        for issue in data["issues"]:
            lines.append(f"  - {issue}")
    if data.get("warnings"):
        lines.append(f"[yellow]Warnings ({len(data['warnings'])}):[/yellow]")
        for warning in data["warnings"]:
            lines.append(f"  - {warning}")
    console.print(
        Panel(
            "\n".join(lines),
            border_style="green" if data.get("valid") else "red",
            title="Hyperframes Validate",
        )
    )


def _format_hyperframes_pipeline(result: Any, project_path: str) -> None:
    data = _model_dump(result)
    lines = [
        f"[bold green]Project:[/bold green] {project_path}",
        f"[bold green]Hyperframes output:[/bold green] {data.get('hyperframes_output', 'N/A')}",
        f"[bold green]Final output:[/bold green] {data.get('final_output', 'N/A')}",
    ]
    if data.get("operations"):
        lines.append(f"[bold green]Post-process ops:[/bold green] {', '.join(data['operations'])}")
    _format_success_panel(lines, title="Hyperframes Pipeline")


def _format_extract_colors(result: Any) -> None:
    data = _model_dump(result)
    table = Table(title="Dominant Colors")
    table.add_column("Color", style="bold cyan")
    table.add_column("Hex")
    table.add_column("RGB")
    table.add_column("CSS Name")
    table.add_column("Coverage")
    for c in data.get("colors", []):
        table.add_row(
            c.get("css_name", ""),
            c.get("hex", ""),
            str(c.get("rgb", "")),
            c.get("css_name", ""),
            f"{c.get('coverage_pct', 0):.1f}%",
        )
    console.print(table)


def _format_generate_palette(result: Any, harmony: str) -> None:
    data = _model_dump(result)
    table = Table(title=f"Color Palette ({harmony})")
    table.add_column("Role", style="bold cyan")
    table.add_column("Hex")
    table.add_row("Base", data.get("base_color", "N/A"))
    palette = data.get("palette", {})
    if isinstance(palette, dict):
        for name, info in palette.items():
            table.add_row(name, info.get("hex", "N/A") if isinstance(info, dict) else str(info))
    console.print(table)


def _format_analyze_product(result: Any) -> None:
    data = _model_dump(result)
    lines = []
    colors = data.get("colors", [])
    if colors:
        lines.append("[bold green]Colors:[/bold green]")
        for c in colors[:5]:
            lines.append(f"  {c.get('hex', '')} ({c.get('css_name', '')}) - {c.get('coverage_pct', 0):.1f}%")
    desc = data.get("description")
    if desc:
        lines.append(f"\n[bold green]AI Description:[/bold green] {desc}")
    _format_success_panel(lines, title="Product Analysis")


def _format_error(e: Exception) -> None:
    """Display error in a styled panel."""
    from ..errors import MCPVideoError

    if isinstance(e, MCPVideoError):
        try:
            data = e.to_dict()
        except Exception as exc:
            logger.debug("MCPVideoError.to_dict() failed in CLI formatting: %s", exc)
            data = {}
        msg = data.get("message", str(e))
        code = data.get("code", "")
        action = data.get("suggested_action", {})
        lines = [f"[bold red]{msg}[/bold red]"]
        if code:
            lines.append(f"[dim]Code: {code}[/dim]")
        if isinstance(action, dict) and action.get("description"):
            lines.append(f"\n[yellow]Suggested fix:[/yellow] {action['description']}")
        err_console.print(Panel("\n".join(lines), border_style="red", title="Error"))
    else:
        err_console.print(Panel(f"[bold red]{e}[/bold red]", border_style="red", title="Error"))
