"""Common execution helpers for the mcp-video CLI."""

from __future__ import annotations

import json
import os
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .formatting import console


def _auto_output(input_path: str, suffix: str) -> str:
    """Generate an output path next to the input file."""
    base, ext = os.path.splitext(input_path)
    return f"{base}_{suffix}{ext}"


def output_json(data: Any) -> None:
    """Print a JSON response, converting Pydantic models first."""
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    print(json.dumps(data, indent=2))


def _parse_json_arg(value: str, arg_name: str = "argument", json_mode: bool = False) -> Any:
    """Parse a JSON string argument, showing a friendly error on failure."""
    if len(value.encode("utf-8")) > 1_048_576:  # 1MB limit
        if json_mode:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": {
                            "type": "input_error",
                            "code": "invalid_json",
                            "message": f"JSON in --{arg_name} exceeds 1MB size limit",
                        },
                    }
                )
            )
        else:
            console.print(f"[bold red]JSON in --{arg_name} exceeds 1MB size limit[/bold red]")
        raise SystemExit(1) from None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        if json_mode:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": {
                            "type": "input_error",
                            "code": "invalid_json",
                            "message": f"Invalid JSON in --{arg_name}: {e}",
                        },
                    }
                )
            )
        else:
            console.print(f"[bold red]Invalid JSON in --{arg_name}: {e}[/bold red]")
        raise SystemExit(1) from None


def _with_spinner(label: str, fn, *args, **kwargs):
    """Run an engine function with a rich spinner."""
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[progress.description]{label}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description=label, total=None)
        return fn(*args, **kwargs)
