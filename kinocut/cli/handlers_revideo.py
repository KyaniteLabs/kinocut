"""CLI handlers for the local Revideo bridge."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from .common import _parse_json_arg, _with_spinner
from .runner import CommandRunner, _out


def _job(value: str, json_mode: bool) -> dict[str, Any]:
    decoded = _parse_json_arg(value, "job-json", json_mode)
    if not isinstance(decoded, dict):
        raise ValidationError("job-json", "must be a JSON object")
    return decoded


def _render_payload(result: Any) -> dict[str, Any]:
    return {"success": True, **result.model_dump(mode="json")}


def handle_revideo_commands(args: Any, *, use_json: bool) -> bool:
    """Dispatch Revideo commands without importing the engine during discovery."""
    runner = CommandRunner(args, use_json)

    def materialize(a: Any, json_mode: bool) -> None:
        from ..revideo_engine import materialize_project

        project = materialize_project(a.dest, _job(a.job_json, json_mode), scene_source=a.scene_source)
        payload = {"success": True, "project_dir": str(project)}
        _out(payload, json_mode, lambda _value: print(f"Materialized Revideo project: {project}"))

    def install(a: Any, json_mode: bool) -> None:
        from ..revideo_engine import install_deps

        _with_spinner("Installing locked Revideo dependencies...", install_deps, a.project_dir, timeout=a.timeout)
        payload = {"success": True, "project_dir": str(a.project_dir)}
        _out(payload, json_mode, lambda _value: print(f"Installed Revideo project: {a.project_dir}"))

    def render(a: Any, json_mode: bool) -> None:
        from ..revideo_engine import render as render_project

        result = _with_spinner(
            "Rendering Revideo project...", render_project, a.project_dir, a.output_path, timeout=a.timeout
        )
        _out(
            result,
            json_mode,
            lambda value: print(f"Rendered Revideo output: {value.output_path}\nSHA-256: {value.output_sha256}"),
            json_transform=_render_payload,
        )

    def render_job(a: Any, json_mode: bool) -> None:
        from ..revideo_engine import render_job as run_job

        result = _with_spinner(
            "Rendering Revideo job...",
            run_job,
            _job(a.job_json, json_mode),
            a.output_path,
            work_dir=a.work_dir,
            scene_source=a.scene_source,
            install_timeout=a.install_timeout,
            render_timeout=a.render_timeout,
        )
        _out(
            result,
            json_mode,
            lambda value: print(f"Rendered Revideo output: {value.output_path}\nSHA-256: {value.output_sha256}"),
            json_transform=_render_payload,
        )

    runner.register("revideo-materialize", materialize)
    runner.register("revideo-install", install)
    runner.register("revideo-render", render)
    runner.register("revideo-render-job", render_job)
    return runner.dispatch()
