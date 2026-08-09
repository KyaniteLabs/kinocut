"""Hyperframes engine — subprocess wrappers calling the Hyperframes CLI.

No pip packages needed — Hyperframes is external (Node.js).

This module owns the command-resolution and subprocess plumbing plus the
operation schema registry. The user-facing public operations (``render``,
``compositions``, ``snapshot``, …) live in :mod:`kinocut.hyperframes_ops` and
are re-exported from here (see the bottom of this file) so that existing
``from ..hyperframes_engine import render`` call sites keep working.

``preview`` and ``validate`` remain in this module because they call
``subprocess``/``shutil`` directly and the test-suite patches those call sites
on this module's namespace (``mcp_video.hyperframes_engine.subprocess.run``).

All file paths should be absolute. Output files are generated automatically
if no output_path is provided.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .errors import (
    HyperframesNotFoundError,
    HyperframesProjectError,
    HyperframesRenderError,
    MCPVideoError,
)
from .hyperframes_models import (
    HyperframesPreviewResult,
    HyperframesValidationResult,
)

HYPERFRAMES_COMMAND_ENV = "MCP_VIDEO_HYPERFRAMES_COMMAND"
HYPERFRAMES_COMMAND_PREFIX = ["hyperframes"]
_HYPERFRAMES_BINARY_NAMES = ("hyperframes", "hyperframes.cmd")
_WINDOWS_COMMAND_PATH_RE = re.compile(r"^([A-Za-z]:\\.*?\.(?:bat|cmd|exe|ps1))(?=\s|$)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Preview lifecycle management
# ---------------------------------------------------------------------------

_active_previews: dict[int, subprocess.Popen[str]] = {}


def _register_preview(port: int, proc: subprocess.Popen[str]) -> None:
    """Track a running preview process so it can be terminated later."""
    old = _active_previews.get(port)
    if old is not None and old.poll() is None:
        stop_preview(port)
    _active_previews[port] = proc


def _terminate_preview(proc: subprocess.Popen[str]) -> None:
    """Best-effort termination of a preview process and its child group."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait(timeout=3)


def stop_preview(port: int) -> bool:
    """Terminate the preview server on *port*. Returns True if a process was stopped."""
    proc = _active_previews.pop(port, None)
    if proc is None:
        return False
    _terminate_preview(proc)
    return True


def stop_all_previews() -> None:
    """Terminate every running preview server (called automatically at exit)."""
    for port in list(_active_previews):
        proc = _active_previews.pop(port, None)
        if proc is not None:
            _terminate_preview(proc)


atexit.register(stop_all_previews)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _validate_project_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise MCPVideoError(
            "Invalid name: must match ^[a-zA-Z0-9_-]+$",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return name


def _find_local_hyperframes_binary(cwd: str | Path | None) -> Path | None:
    start = Path(cwd) if cwd is not None else Path.cwd()
    try:
        start = start.resolve()
    except OSError:
        start = start.absolute()
    if start.is_file():
        start = start.parent

    for base in (start, *start.parents):
        for name in _HYPERFRAMES_BINARY_NAMES:
            candidate = base / "node_modules" / ".bin" / name
            if candidate.is_file() and (name.endswith(".cmd") or os.access(candidate, os.X_OK)):
                return candidate
    return None


def _split_configured_hyperframes_command(value: str) -> list[str]:
    configured = value.strip()
    if not configured:
        return []

    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return [str(candidate)]

    windows_match = _WINDOWS_COMMAND_PATH_RE.match(configured)
    if windows_match:
        command = windows_match.group(1)
        rest = configured[windows_match.end() :].strip()
        if not rest:
            return [command]
        return [command, *[part.strip('"') for part in shlex.split(rest, posix=False)]]

    return [part.strip('"') for part in shlex.split(configured, posix=os.name != "nt")]


def _hyperframes_command_prefix(
    cwd: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> list[str]:
    env_map = os.environ if env is None else env
    which_fn = shutil.which if which is None else which
    configured = env_map.get(HYPERFRAMES_COMMAND_ENV)
    if configured is not None:
        command = _split_configured_hyperframes_command(configured)
        if command:
            return command
        raise HyperframesNotFoundError(f"{HYPERFRAMES_COMMAND_ENV} is set but empty")

    local_binary = _find_local_hyperframes_binary(cwd)
    if local_binary is not None:
        return [str(local_binary)]

    path_binary = which_fn("hyperframes")
    if path_binary:
        return [path_binary]

    raise HyperframesNotFoundError(
        "Hyperframes CLI not found. Install a pinned Hyperframes package with "
        "node_modules/.bin/hyperframes, add hyperframes to PATH, or set "
        f"{HYPERFRAMES_COMMAND_ENV}."
    )


def _require_node() -> None:
    if shutil.which("node") is None:
        raise HyperframesNotFoundError("node not found on PATH")


def _require_hyperframes_deps(cwd: str | Path | None = None) -> None:
    """Raise a helpful error if Node.js/Hyperframes are not available."""
    _require_node()
    _hyperframes_command_prefix(cwd=cwd)


def _find_entry_point(project: Path) -> Path:
    """Locate the Hyperframes entry point (index.html or any HTML with data-composition-id)."""
    for candidate in ["index.html", "composition.html", "demo.html"]:
        if (project / candidate).is_file():
            return project / candidate
    # Fallback: any HTML file
    for f in project.iterdir():
        if f.suffix == ".html" and f.is_file():
            return f
    raise HyperframesProjectError(str(project), "Could not find entry point (no .html file)")


def _validate_project(project_path: str) -> tuple[Path, Path]:
    """Check that the project directory has the expected structure.

    Returns (project_dir, entry_point) tuple.
    """
    p = Path(project_path).resolve()
    if not p.is_dir():
        raise HyperframesProjectError(str(p), "Directory does not exist")
    entry_point = _find_entry_point(p)
    return p, entry_point


def _run_hyperframes(
    args: list[str],
    cwd: str | Path,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Run a Hyperframes command and return the CompletedProcess."""
    cmd = [*_hyperframes_command_prefix(cwd=cwd), *args]
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            # Never inherit the caller's stdin: when invoked from an MCP server
            # there is no TTY, so a stray interactive prompt would block forever.
            stdin=subprocess.DEVNULL,
            # `init` runs a network AI-skills check that the --skip-skills flag
            # does not currently disable; this env var is the supported opt-out.
            env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"},
        )
    except subprocess.TimeoutExpired:
        raise HyperframesRenderError(" ".join(cmd), -1, "Render timed out") from None
    except FileNotFoundError:
        raise HyperframesNotFoundError(f"{cmd[0]} command not found") from None


# ---------------------------------------------------------------------------
# Operation schema registry
# ---------------------------------------------------------------------------

_SCHEMA: dict[str, dict[str, Any]] = {
    "render": {
        "subcommand": "render",
        "positional": ["project_path"],
        "flags": {
            "output": "output_path",
            "fps": "fps",
            "composition": "composition",
            "quality": "quality",
            "format": "format",
            "resolution": "resolution",
            "workers": "workers",
            "crf": "crf",
            "video-bitrate": "video_bitrate",
            "variables": "variables",
            "variables-file": "variables_file",
            "max-concurrent-renders": "max_concurrent_renders",
        },
        "switches": {
            "docker": "docker",
            "hdr": "hdr",
            "sdr": "sdr",
            "gpu": "gpu",
            "browser-gpu": "browser_gpu",
            "no-browser-gpu": "no_browser_gpu",
            "quiet": "quiet",
            "strict": "strict",
            "strict-all": "strict_all",
            "strict-variables": "strict_variables",
        },
        "timeout": 600,
    },
    "compositions": {
        "subcommand": "compositions",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
    "snapshot": {
        "subcommand": "snapshot",
        "positional": ["project_path"],
        "flags": {
            "frames": "frames",
            "at": "at_csv",
            "timeout": "timeout_ms",
            "variables": "variables",
            "variables-file": "variables_file",
        },
        "timeout": 120,
    },
    "inspect": {
        "subcommand": "inspect",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "flags": {
            "samples": "samples",
            "at": "at_csv",
            "tolerance": "tolerance",
            "timeout": "timeout_ms",
            "max-issues": "max_issues",
        },
        "switches": {
            "strict": "strict",
            "collapse-static": "collapse_static",
            "no-collapse-static": "no_collapse_static",
        },
        "timeout": 120,
    },
    "info": {
        "subcommand": "info",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
    "catalog": {
        "subcommand": "catalog",
        "fixed": ["--json"],
        "flags": {
            "type": "item_type",
            "tag": "tag",
        },
        "cwd_key": None,
        "timeout": 60,
    },
    "capture": {
        "subcommand": "capture",
        "positional": ["url"],
        "fixed": ["--json"],
        "flags": {
            "output": "output",
            "max-screenshots": "max_screenshots",
            "timeout": "timeout_ms",
        },
        "switches": {
            "skip-assets": "skip_assets",
        },
        "cwd_key": None,
        "timeout": 180,
    },
    "transcribe": {
        "subcommand": "transcribe",
        "positional": ["input_path"],
        "fixed": ["--json"],
        "flags": {
            "dir": "project_path",
            "model": "model",
            "language": "language",
        },
        "cwd_key": None,
        "timeout": 600,
    },
    "tts": {
        "subcommand": "tts",
        "optional_positional": ["text_or_file"],
        "fixed": ["--json"],
        "flags": {
            "output": "output_path",
            "voice": "voice",
            "speed": "speed",
            "lang": "language",
        },
        "switches": {
            "list": "list_voices",
        },
        "cwd_key": None,
        "timeout": 600,
    },
    "remove-background": {
        "subcommand": "remove-background",
        "positional": ["input_path"],
        "fixed": ["--json"],
        "flags": {
            "output": "output_path",
            "background-output": "background_output_path",
            "device": "device",
            "quality": "quality",
        },
        "switches": {
            "info": "info",
        },
        "cwd_key": None,
        "timeout": 900,
    },
    "doctor": {
        "subcommand": "doctor",
        "fixed": ["--json"],
        "cwd_key": None,
        "timeout": 60,
    },
    "benchmark": {
        "subcommand": "benchmark",
        "positional": ["project_path"],
        "flags": {
            "output": "output_path",
            "runs": "runs",
        },
        "switches": {
            "json": "json_output",
        },
        "timeout": 900,
    },
    "add": {
        "subcommand": "add",
        "positional": ["block_name"],
        "flags": {
            "dir": "project_path",
        },
        "switches": {
            "no-clipboard": "no_clipboard",
        },
        "fixed": ["--json"],
        "timeout": 60,
    },
    "init": {
        "subcommand": "init",
        "positional": ["name"],
        "flags": {
            "example": "template",
            "video": "video",
            "audio": "audio",
            "model": "model",
            "language": "language",
            "resolution": "resolution",
        },
        "switches": {
            "tailwind": "tailwind",
            # Opt-in: emit the skip flag only when the caller requests it via
            # create_project(skip_transcribe=True).
            "skip-transcribe": "skip_transcribe",
        },
        # `init` prompts interactively by default and can implicitly launch
        # Whisper; always pass --non-interactive so the MCP subprocess scaffolds
        # a project without ever blocking on input. --skip-transcribe is opt-in
        # above, so the public default (skip_transcribe=False) omits it.
        "fixed": ["--non-interactive", "--skip-skills"],
        "cwd_key": "output_dir",
        "timeout": 120,
    },
    "lint": {
        "subcommand": "lint",
        "positional": ["project_path"],
        "fixed": ["--json"],
        "timeout": 60,
    },
}


def _hyperframes_op(
    operation: str,
    **kwargs: Any,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run a hyperframes subcommand from the schema registry.

    Returns (completed_process, cwd_path).
    """
    spec = _SCHEMA.get(operation)
    if spec is None:
        raise MCPVideoError(
            f"Unknown hyperframes operation: {operation}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    _require_node()

    cwd_key = spec.get("cwd_key", "project_path")
    if cwd_key is None:
        cwd = Path(kwargs.get("cwd") or os.getcwd()).resolve()
    else:
        cwd_val = kwargs.get(cwd_key)
        if cwd_val is None:
            raise MCPVideoError(
                f"Missing required parameter: {cwd_key}",
                error_type="validation_error",
                code="invalid_parameter",
            )

        if cwd_key == "project_path":
            cwd, _entry_point = _validate_project(cwd_val)
            kwargs[cwd_key] = str(cwd)
        else:
            cwd = Path(cwd_val).resolve()
            kwargs[cwd_key] = str(cwd)

    _require_hyperframes_deps(cwd=cwd)

    args: list[str] = [spec["subcommand"]]

    for pos_key in spec.get("positional", []):
        val = kwargs.get(pos_key)
        if val is None:
            raise MCPVideoError(
                f"Missing required parameter: {pos_key}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        args.append(str(val))

    for pos_key in spec.get("optional_positional", []):
        val = kwargs.get(pos_key)
        if val:
            args.append(str(val))

    for flag, kw_key in spec.get("flags", {}).items():
        val = kwargs.get(kw_key)
        if val is not None:
            args.extend([f"--{flag}", _format_cli_value(val)])

    for flag, kw_key in spec.get("switches", {}).items():
        if kwargs.get(kw_key):
            args.append(f"--{flag}")

    for item in spec.get("fixed", []):
        args.append(item)

    for flag, compute in spec.get("computed", {}).items():
        args.extend([f"--{flag}", _format_cli_value(compute(kwargs))])

    result = _run_hyperframes(args, cwd=cwd, timeout=spec.get("timeout", 600))
    if result.returncode != 0:
        raise HyperframesRenderError(" ".join(args), result.returncode, result.stderr)

    return result, cwd


def _format_cli_value(value: Any) -> str:
    """Format Hyperframes CLI flag values without introducing false precision."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# Preview & validation (remain here: they call subprocess/shutil directly)
# ---------------------------------------------------------------------------


def preview(
    project_path: str,
    port: int = 3002,
    startup_timeout: int = 10,
) -> HyperframesPreviewResult:
    """Launch Hyperframes preview studio (non-blocking)."""
    if port < 1024 or port > 65535:
        raise HyperframesProjectError(str(project_path), "Preview port must be between 1024 and 65535")
    _require_node()
    project, _entry_point = _validate_project(project_path)
    _require_hyperframes_deps(cwd=project)
    stop_preview(port)

    cmd = [*_hyperframes_command_prefix(cwd=project), "preview", str(project), "--port", str(port)]
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(project),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


    time.sleep(min(startup_timeout, 2))
    if proc.poll() is not None:
        raise HyperframesProjectError(str(project), "Hyperframes preview exited immediately")
    _register_preview(port, proc)

    return HyperframesPreviewResult(
        url=f"http://localhost:{port}",
        port=port,
        project_path=str(project),
        pid=proc.pid,
    )


def validate(
    project_path: str,
) -> HyperframesValidationResult:
    """Validate a Hyperframes project for rendering readiness."""
    issues: list[str] = []
    warnings: list[str] = []

    p = Path(project_path).resolve()

    if not p.is_dir():
        issues.append("Project directory does not exist")
        return HyperframesValidationResult(
            valid=False,
            issues=issues,
            warnings=warnings,
            project_path=str(p),
        )

    try:
        _find_entry_point(p)
    except HyperframesProjectError:
        issues.append("No HTML entry point found (expected index.html)")

    # Check Node.js/Hyperframes
    if shutil.which("node") is None:
        issues.append("Node.js not found on PATH")
    try:
        _hyperframes_command_prefix(cwd=p)
    except HyperframesNotFoundError as e:
        issues.append(f"Hyperframes CLI not found: {e}")

    # Run hyperframes lint if deps are available
    if shutil.which("node") is not None and not any("Hyperframes CLI not found" in issue for issue in issues):
        try:
            result = _run_hyperframes(["lint", str(p), "--json"], cwd=p, timeout=60)
            if result.returncode != 0:
                try:
                    lint_data = json.loads(result.stdout)
                    for finding in lint_data.get("errors", []):
                        issues.append(f"lint: {finding}")
                    for finding in lint_data.get("warnings", []):
                        warnings.append(f"lint: {finding}")
                except json.JSONDecodeError:
                    issues.append(f"lint failed: {result.stderr[:200]}")
        except Exception as e:
            warnings.append(f"Could not run hyperframes lint: {e}")

    valid = len(issues) == 0

    return HyperframesValidationResult(
        valid=valid,
        issues=issues,
        warnings=warnings,
        project_path=str(p),
    )


# Public API is implemented in hyperframes_ops and re-exported here so existing
# `from ..hyperframes_engine import render` call sites keep working. The names
# are resolved lazily via __getattr__ (PEP 562) rather than a top-level import
# so that *either* module may be imported first without a circular-import
# failure: hyperframes_ops imports private primitives (_hyperframes_op,
# _require_node, _validate_project, ...) defined above, and engine never
# imports hyperframes_ops at module-load time. monkeypatch.setattr on this
# module still wins because it writes directly into __dict__, which __getattr__
# never shadows.
_RE_EXPORTED_OPS = frozenset(
    {
        "add_block",
        "benchmark",
        "capture",
        "catalog",
        "compositions",
        "create_project",
        "doctor",
        "info",
        "inspect",
        "remove_background",
        "render",
        "render_and_post",
        "snapshot",
        "still",
        "transcribe",
        "tts",
    }
)


def __getattr__(name: str) -> Any:
    if name in _RE_EXPORTED_OPS:
        from . import hyperframes_ops

        value = getattr(hyperframes_ops, name)
        globals()[name] = value  # cache: later lookups bypass __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _RE_EXPORTED_OPS)
