"""Run Hyperframes commands and return typed operation results."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_COMPOSITION_FPS, DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL
from ..errors import HyperframesNotFoundError, HyperframesRenderError, HyperframesProjectError, MCPVideoError
from ..ffmpeg_helpers import _atomic_output, _open_staged_writer, _validate_output_path
from ..offline import is_offline_mode
from ..request_log import redact_text
from ..validation_errors import reason
from ..object_matte.catalog import (
    _assert_hf_remove_background_flags,
    _normalize_mask_interval,
    _resolve_remove_background_model,
    background_catalog,
    uses_object_backend,
)
from .artifacts import _default_render_output, _render_output_exists, _snapshot_pngs
from .models import (
    HyperframesBlockResult,
    HyperframesJsonResult,
    HyperframesProjectResult,
    HyperframesRenderResult,
    HyperframesSnapshotResult,
    HyperframesStillResult,
    HyperframesValidationResult,
)
from .results import _doctor_result, _hf_remove_background_result, _json_result
from .runner import (
    _hyperframes_command_prefix,
    _hyperframes_op,
    _require_hyperframes_deps,
    _require_node,
    _run_hyperframes,
    current_runner,
)
from .validation import (
    _find_entry_point,
    _validate_project,
    _validate_project_name,
    _validate_variables_file,
    validate_inspect_options,
    validate_render_options,
    validate_tts_options,
)


def _require_online(operation: str) -> None:
    if is_offline_mode():
        raise MCPVideoError(
            f"Hyperframes {operation} requires network access and is blocked in offline mode (KINOCUT_OFFLINE=1)",
            error_type="validation_error",
            code="offline_network_blocked",
        )


def _csv(values: list[float] | list[str] | None) -> str | None:
    if not values:
        return None
    return ",".join(str(v) for v in values)


def _build_render_result(
    output_path: str,
    format: str | None,
    render_time: float,
    effective_resolution: str | None,
    width: int | None,
    height: int | None,
) -> HyperframesRenderResult:
    """Build render result from output metadata."""
    try:
        size = os.path.getsize(output_path) if os.path.isfile(output_path) else None
        size_mb = round(size / (1024 * 1024), 2) if size is not None else None
    except OSError:
        size_mb = None

    reported_resolution = effective_resolution
    if width and height:
        reported_resolution = f"{width}x{height}"

    if not _render_output_exists(output_path, format):
        return HyperframesRenderResult(
            output_path=output_path,
            codec=format or "h264",
            size_mb=None,
            render_time=render_time,
            resolution=reported_resolution,
            success=False,
        )

    return HyperframesRenderResult(
        output_path=output_path,
        codec=format or "h264",
        size_mb=size_mb,
        render_time=render_time,
        resolution=reported_resolution,
    )


def render(
    project_path: str,
    output_path: str | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
    composition: str | None = None,
    quality: str | None = None,
    format: str | None = None,
    resolution: str | None = None,
    workers: str | int | None = None,
    crf: int | None = None,
    video_bitrate: str | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
    docker: bool = False,
    hdr: bool = False,
    sdr: bool = False,
    gpu: bool = False,
    browser_gpu: bool = False,
    no_browser_gpu: bool = False,
    quiet: bool = False,
    strict: bool = False,
    strict_all: bool = False,
    max_concurrent_renders: int | None = None,
    strict_variables: bool = False,
) -> HyperframesRenderResult:
    """Render a Hyperframes composition to video."""
    effective_resolution = validate_render_options(
        quality=quality,
        format=format,
        resolution=resolution,
        width=width,
        height=height,
        crf=crf,
        max_concurrent_renders=max_concurrent_renders,
        browser_gpu=browser_gpu,
        no_browser_gpu=no_browser_gpu,
        hdr=hdr,
        sdr=sdr,
    )
    _require_node()
    if output_path is None:
        output_path = _default_render_output(project_path, format)
    output_path = _validate_output_path(str(Path(output_path).expanduser().absolute()))

    variables_file = _validate_variables_file(variables_file)

    start_time = time.time()
    _result, _project = _hyperframes_op(
        "render",
        project_path=project_path,
        output_path=output_path,
        fps=fps,
        composition=composition,
        quality=quality,
        format=format,
        resolution=effective_resolution,
        workers=workers,
        crf=crf,
        video_bitrate=video_bitrate,
        variables=variables,
        variables_file=variables_file,
        docker=docker,
        hdr=hdr,
        sdr=sdr,
        gpu=gpu,
        browser_gpu=browser_gpu,
        no_browser_gpu=no_browser_gpu,
        quiet=quiet,
        strict=strict,
        strict_all=strict_all,
        max_concurrent_renders=max_concurrent_renders,
        strict_variables=strict_variables,
    )

    render_time = round(time.time() - start_time, 1)

    return _build_render_result(output_path, format, render_time, effective_resolution, width, height)


# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------


def still(
    project_path: str,
    output_path: str | None = None,
    frame: int = 0,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> HyperframesStillResult:
    """Render a single frame from a Hyperframes composition.

    A requested output is resolved from the caller's working directory and
    copied atomically, so subsequent snapshots cannot replace that artifact.
    """
    destination = _validate_output_path(str(Path(output_path).expanduser().absolute())) if output_path else None
    seconds = frame / DEFAULT_COMPOSITION_FPS
    snap = snapshot(project_path, at=[seconds], frames=1, variables=variables, variables_file=variables_file)
    if not snap.success or not snap.frame_paths or not Path(snap.frame_paths[0]).is_file():
        raise HyperframesRenderError("snapshot", 1, "", reason="Hyperframes snapshot produced no still image")
    actual_output = snap.frame_paths[0]
    if destination and Path(destination) != Path(actual_output).absolute():
        try:
            with (
                _atomic_output(destination) as temporary,
                open(actual_output, "rb") as src_fh,
                _open_staged_writer(temporary) as dst_fh,
            ):
                shutil.copyfileobj(src_fh, dst_fh)
        except OSError as exc:
            raise HyperframesRenderError("snapshot", 1, "", reason="Could not copy requested still image") from exc
        actual_output = destination

    return HyperframesStillResult(
        output_path=actual_output,
        frame=frame,
    )


def snapshot(
    project_path: str,
    frames: int = 5,
    at: list[float] | None = None,
    timeout_ms: int | None = None,
    variables: Any | None = None,
    variables_file: str | None = None,
) -> HyperframesSnapshotResult:
    """Capture key frames as PNG screenshots for visual verification."""
    _require_node()
    project, _entry_point = _validate_project(project_path)
    snapshot_dir = project / "snapshots"
    before = set(snapshot_dir.glob("*.png")) if snapshot_dir.is_dir() else set()
    at_csv = _csv(at)
    variables_file = _validate_variables_file(variables_file)
    _hyperframes_op(
        "snapshot",
        project_path=project_path,
        frames=frames if at_csv is None else None,
        at_csv=at_csv,
        timeout_ms=timeout_ms,
        variables=variables,
        variables_file=variables_file,
    )
    frame_paths = _snapshot_pngs(project, before)
    if not frame_paths:
        raise HyperframesRenderError(
            "hyperframes snapshot",
            0,
            "",
            reason="Hyperframes exited successfully but wrote no new snapshot frames; stale frames were not returned as current",
        )
    return HyperframesSnapshotResult(
        frame_paths=frame_paths,
        output_dir=str(snapshot_dir),
        frames=frames,
        at=at or [],
    )


def inspect(
    project_path: str,
    samples: int = 9,
    at: list[float] | None = None,
    tolerance: int = 2,
    timeout_ms: int | None = None,
    max_issues: int = 80,
    collapse_static: bool = False,
    no_collapse_static: bool = False,
    strict: bool = False,
) -> HyperframesJsonResult:
    """Inspect rendered layout for text and container overflow."""
    validate_inspect_options(samples, collapse_static, no_collapse_static)
    result, _project = _hyperframes_op(
        "inspect",
        project_path=project_path,
        samples=samples,
        at_csv=_csv(at),
        tolerance=tolerance,
        timeout_ms=timeout_ms,
        max_issues=max_issues,
        collapse_static=collapse_static,
        no_collapse_static=no_collapse_static,
        strict=strict,
    )
    return _json_result("inspect", result)


def info(project_path: str) -> HyperframesJsonResult:
    """Return Hyperframes project metadata."""
    result, _project = _hyperframes_op("info", project_path=project_path)
    return _json_result("info", result)


# ---------------------------------------------------------------------------
# Catalog, capture & media
# ---------------------------------------------------------------------------


def catalog(item_type: str | None = None, tag: str | None = None) -> HyperframesJsonResult:
    """Browse Hyperframes catalog blocks/components."""
    _require_online("catalog")
    result, _cwd = _hyperframes_op("catalog", item_type=item_type, tag=tag)
    return _json_result("catalog", result)


def capture(
    url: str,
    output: str | None = None,
    skip_assets: bool = False,
    max_screenshots: int | None = None,
    timeout_ms: int | None = None,
) -> HyperframesJsonResult:
    """Capture a website as editable Hyperframes components."""
    _require_online("capture")
    from ..ai_engine.download import _is_safe_url

    if not _is_safe_url(url):
        raise MCPVideoError(
            "Capture URL blocked by SSRF policy",
            error_type="validation_error",
            code="ssrf_blocked",
        )
    result, _cwd = _hyperframes_op(
        "capture",
        url=url,
        output=output,
        skip_assets=skip_assets,
        max_screenshots=max_screenshots,
        timeout_ms=timeout_ms,
    )
    return _json_result("capture", result)


def transcribe(
    input_path: str,
    project_path: str | None = None,
    model: str | None = None,
    language: str | None = None,
) -> HyperframesJsonResult:
    """Transcribe audio/video to word-level timestamps or import transcript files."""
    result, _cwd = _hyperframes_op(
        "transcribe",
        input_path=input_path,
        project_path=project_path,
        model=model,
        language=language,
    )
    return _json_result("transcribe", result)


def tts(
    text_or_file: str | None = None,
    output_path: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
    language: str | None = None,
    list_voices: bool = False,
) -> HyperframesJsonResult:
    """Generate speech audio from text using Hyperframes local TTS."""
    _require_online("tts")
    validate_tts_options(text_or_file, speed, list_voices)
    result, _cwd = _hyperframes_op(
        "tts",
        text_or_file=text_or_file,
        output_path=output_path,
        voice=voice,
        speed=speed,
        language=language,
        list_voices=list_voices,
    )
    return _json_result("tts", result)


def _remove_background_info() -> HyperframesJsonResult:
    payload = background_catalog()
    return HyperframesJsonResult(command="remove-background", data=payload, stdout=json.dumps(payload, sort_keys=True))


def remove_background(
    input_path: str | None = None,
    output_path: str | None = None,
    background_output_path: str | None = None,
    device: str = "auto",
    quality: str = "balanced",
    info: bool = False,
    model: str | None = None,
    mask_interval: int = DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL,
    equipment_overlay: str | None = None,
    fail_if_equipment_on_subject: bool = False,
) -> HyperframesJsonResult:
    """Cut a person or a product out of a still or video.

    Default model is people (`u2net_human_seg`) via Hyperframes. Products and
    other objects use `birefnet-general` (Kinocut ONNX, `kinocut[object-matte]==2.0.1`).
    """
    if info:
        return _remove_background_info()
    resolved = _resolve_remove_background_model(model)
    if not input_path:
        raise MCPVideoError(
            "input_path is required unless info is true",
            error_type="validation_error",
            code="invalid_parameter",
        )
    interval = _normalize_mask_interval(mask_interval)
    if uses_object_backend(resolved):
        from ..object_matte import run_object_matte

        return run_object_matte(
            input_path=input_path,
            output_path=output_path,
            background_output_path=background_output_path,
            device=device,
            quality=quality,
            mask_interval=interval,
            equipment_overlay=equipment_overlay,
            fail_if_equipment_on_subject=fail_if_equipment_on_subject,
        )
    _require_online("remove-background")
    _assert_hf_remove_background_flags(
        mask_interval=interval,
        equipment_overlay=equipment_overlay,
        fail_if_equipment_on_subject=fail_if_equipment_on_subject,
    )
    result, _cwd = _hyperframes_op(
        "remove-background",
        input_path=input_path,
        output_path=output_path,
        background_output_path=background_output_path,
        device=device,
        quality=quality,
    )
    return _hf_remove_background_result(result)


def doctor() -> HyperframesJsonResult:
    """Run Hyperframes environment diagnostics."""
    result, _cwd = _hyperframes_op("doctor")
    return _doctor_result(result)


def benchmark(
    project_path: str,
    output_path: str | None = None,
    runs: int | None = None,
    json_output: bool = True,
) -> HyperframesJsonResult:
    """Benchmark Hyperframes render speed and output size."""
    result, _project = _hyperframes_op(
        "benchmark",
        project_path=project_path,
        output_path=output_path,
        runs=runs,
        json_output=json_output,
    )
    return _json_result("benchmark", result)


# ---------------------------------------------------------------------------
# Project scaffolding & pipeline
# ---------------------------------------------------------------------------


def create_project(
    name: str,
    output_dir: str | None = None,
    template: str = "blank",
    video: str | None = None,
    audio: str | None = None,
    skip_transcribe: bool = False,
    model: str | None = None,
    language: str | None = None,
    tailwind: bool = False,
    resolution: str | None = None,
) -> HyperframesProjectResult:
    """Scaffold a new Hyperframes project."""
    name = _validate_project_name(name)
    if output_dir is None:
        output_dir = os.getcwd()
    output_dir = _validate_output_path(output_dir)
    project_dir = Path(output_dir) / name
    _validate_output_path(str(project_dir))

    _require_hyperframes_deps(cwd=output_dir)

    if project_dir.exists() and any(project_dir.iterdir()):
        # A printed warning is not a gate: refuse rather than overwrite scaffolding and renders.
        raise MCPVideoError(
            "Project directory already exists and is not empty",
            error_type="validation_error",
            code="output_exists",
            suggested_action={
                "auto_fix": False,
                "description": "Choose another project name or output directory, or remove the existing project yourself.",
            },
        )

    project_dir.mkdir(parents=True, exist_ok=True)

    _hyperframes_op(
        "init",
        name=name,
        template=template,
        output_dir=output_dir,
        video=video,
        audio=audio,
        skip_transcribe=skip_transcribe,
        model=model,
        language=language,
        tailwind=tailwind,
        resolution=resolution,
    )

    # Discover created files
    files: list[str] = []
    if project_dir.exists():
        for f in project_dir.rglob("*"):
            if f.is_file():
                files.append(str(f.relative_to(project_dir)))

    return HyperframesProjectResult(
        project_path=str(project_dir),
        template=template,
        files=files,
    )


def add_block(
    project_path: str,
    block_name: str,
    no_clipboard: bool = False,
) -> HyperframesBlockResult:
    """Install a block from the Hyperframes catalog."""
    _require_online("add")
    result, project = _hyperframes_op(
        "add",
        project_path=project_path,
        block_name=block_name,
        no_clipboard=no_clipboard,
    )

    files_added: list[str] = []
    try:
        add_data = json.loads(result.stdout)
        files_added = add_data.get("files", [])
    except json.JSONDecodeError:
        pass

    return HyperframesBlockResult(
        project_path=str(project),
        block_name=block_name,
        files_added=files_added,
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
    node_available = current_runner().which("node") is not None
    if not node_available:
        issues.append("Node.js not found on PATH")
    try:
        _hyperframes_command_prefix(cwd=p)
    except HyperframesNotFoundError as e:
        issues.append(f"Hyperframes CLI not found: {e}")

    # Run hyperframes lint if deps are available
    if node_available and not any("Hyperframes CLI not found" in issue for issue in issues):
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
                    issues.append(f"lint failed: {redact_text(result.stderr[:200])}")
        except Exception as e:
            issues.append(f"Could not run hyperframes lint: {redact_text(reason(e))}")

    valid = len(issues) == 0

    return HyperframesValidationResult(
        valid=valid,
        issues=issues,
        warnings=warnings,
        project_path=str(p),
    )
