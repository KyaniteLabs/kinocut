"""Rich renderables for quality verdicts and human release checkpoints."""

from typing import Any

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table


def quality_report_renderables(data: Any) -> tuple[Table, str]:
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
    return table, f"[bold]Overall: {overall}[/bold]"


def release_checkpoint_renderable(data: Any) -> Panel | str:
    if not isinstance(data, dict):
        data = {}
    if data.get("error"):
        message = data["error"].get("message", "release checkpoint failed")
        return f"[bold red]RELEASE CHECKPOINT FAILED:[/bold red] {escape(str(message))}"
    quality = data.get("quality") or {}
    score = quality.get("overall_score")
    lines = []
    if score is not None:
        lines.append(f"[bold green]Quality score:[/bold green] {score}")
    if data.get("thumbnail"):
        lines.append(f"[bold green]Thumbnail:[/bold green] {data['thumbnail']}")
    storyboard = data.get("storyboard") or {}
    if isinstance(storyboard, dict) and storyboard.get("output_path"):
        lines.append(
            f"[bold green]Storyboard:[/bold green] {storyboard['output_path']} ({storyboard.get('count', '?')} frames)"
        )
    if data.get("review_required"):
        lines.append("[bold yellow]Review required:[/bold yellow] inspect the artifacts before publishing.")
    if data.get("instructions"):
        lines.append(escape(str(data["instructions"])))
    return Panel("\n".join(lines), title="Release Checkpoint", border_style="green")


def design_quality_panel(data: Any) -> Panel:
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
    return Panel("\n".join(lines), title="Design Quality", border_style="green")
