"""Rich output formatters for dedicated rescue commands."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

console = Console()


def _model_dump(result: Any) -> Any:
    return result.model_dump() if hasattr(result, "model_dump") else result


def _format_success_panel(content: list[str], *, title: str, border_style: str) -> None:
    console.print(Panel("\n".join(content), border_style=border_style, title=title))


def _repair_ids(records: Any) -> list[str]:
    if not isinstance(records, list):
        return []
    return [str(record["id"]) for record in records if isinstance(record, dict) and record.get("id")]


def _unavailable_capabilities(capabilities: Any) -> list[str]:
    if not isinstance(capabilities, dict):
        return []
    unavailable: list[str] = []
    for group, details in capabilities.items():
        if not isinstance(details, dict):
            continue
        if details.get("available") is False:
            unavailable.append(str(group))
        for name, value in details.items():
            if name == "available":
                continue
            if value is False or (isinstance(value, dict) and value.get("available") is False):
                unavailable.append(f"{group}.{name}")
    return unavailable


def format_rescue_plan(result: Any) -> None:
    """Display the diagnosis and approval boundary of a rescue plan."""
    data = result if isinstance(result, dict) else _model_dump(result)
    source = data.get("source") or {}
    buckets = (
        ("Safe", "safe_repairs"),
        ("Recommended", "recommendations"),
        ("Unavailable", "unavailable_repairs"),
        ("Blocked", "blocked_repairs"),
    )
    counts = ", ".join(f"{label.lower()}={len(data.get(key, []))}" for label, key in buckets)
    safe_ids = _repair_ids(data.get("safe_repairs"))
    unavailable = _unavailable_capabilities(data.get("capabilities"))
    previews = [
        str(record["path"])
        for record in data.get("preview_artifacts", [])
        if isinstance(record, dict) and record.get("path")
    ]
    estimate = data.get("estimate") or {}
    lines = [
        f"[bold green]Source:[/bold green] {escape(str(source.get('path', '(unknown)')))}",
        f"[bold green]Dispositions:[/bold green] {escape(counts)}",
        f"[bold green]Safe repair IDs:[/bold green] {escape(', '.join(safe_ids)) if safe_ids else '(none)'}",
        f"[bold green]Unavailable capabilities:[/bold green] {escape(', '.join(unavailable)) if unavailable else '(none)'}",
        f"[bold green]Previews:[/bold green] {escape(', '.join(previews)) if previews else '(none)'}",
        f"[bold green]Estimate:[/bold green] {estimate.get('seconds', 0)} seconds "
        f"({escape(str(estimate.get('confidence', 'unknown')))})",
        "[bold yellow]Review this plan before rendering.[/bold yellow]",
    ]
    _format_success_panel(lines, title="Rescue Plan", border_style="yellow")


def format_rescue_render(result: Any) -> None:
    """Display a completed rescue package and verification summary."""
    data = result if isinstance(result, dict) else _model_dump(result)
    package = data.get("package") or {}
    verification = data.get("verification") or []
    passed = sum(1 for check in verification if isinstance(check, dict) and check.get("passed"))
    lines = [
        f"[bold green]Status:[/bold green] {escape(str(data.get('status')))}",
        f"[bold green]Package:[/bold green] {escape(str(package.get('path') or '(not promoted)'))}",
        f"[bold green]Applied:[/bold green] {escape(', '.join(data.get('applied_repair_ids', []))) or '(none)'}",
        f"[bold green]Skipped:[/bold green] {escape(', '.join(data.get('skipped_repair_ids', []))) or '(none)'}",
        f"[bold green]Verification:[/bold green] {passed}/{len(verification)} checks passed",
        f"[bold green]Receipt:[/bold green] "
        f"{escape(str(data.get('receipt_path') or 'rescue-receipt.json inside package'))}",
    ]
    _format_success_panel(lines, title="Rescue Render", border_style="green")


def format_rescue_inspect(result: Any) -> None:
    """Display rescue integrity, verification, privacy, and resume state."""
    data = result if isinstance(result, dict) else _model_dump(result)
    integrity = data.get("integrity") or {}
    verification = data.get("verification") or []
    failures = [
        str(check.get("id") or check.get("name") or "unknown")
        for check in verification
        if isinstance(check, dict) and not check.get("passed")
    ]
    privacy = data.get("privacy") or {}
    resume = data.get("resume") or {}
    cleanup = data.get("cleanup") or {}
    resumable = resume.get("resumable", resume.get("used", False))
    retained = cleanup.get("intermediates_retained", bool(cleanup.get("intermediates")))
    lines = [
        f"[bold green]Status:[/bold green] {escape(str(data.get('status')))}",
        f"[bold green]Integrity:[/bold green] all matching={integrity.get('all_matching')}",
        f"[bold green]Verification failures:[/bold green] "
        f"{escape(', '.join(failures)) if failures else '(none)'}",
        f"[bold green]Local only:[/bold green] {privacy.get('local_only')}",
        f"[bold green]Resumable:[/bold green] {resumable}",
        f"[bold green]Intermediates retained:[/bold green] {retained}",
    ]
    border = "yellow" if failures or integrity.get("all_matching") is False else "green"
    _format_success_panel(lines, title="Rescue Inspect", border_style=border)
