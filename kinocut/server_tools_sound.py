"""MCP adapters for the thin kinocut_sound S12 public join."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


def _invoke(name: str, **kwargs: Any) -> dict[str, Any]:
    from kinocut_sound.public import invoke_sound_operation

    return invoke_sound_operation(name, **kwargs)


@mcp.tool()
@_safe_tool
def sound_capabilities() -> dict[str, Any]:
    """Discover the bounded public sound operation set (local-first, JSON-safe)."""
    return _result(_invoke("sound-capabilities"))


@mcp.tool()
@_safe_tool
def sound_plan_validate(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a SoundPlan payload (or a built-in minimal plan when omitted)."""
    return _result(_invoke("sound-plan-validate", plan=plan))


@mcp.tool()
@_safe_tool
async def sound_voice_batch(
    plan: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Retain local caption speech from a request, or run the synthetic plan demo."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound.public.dub_job import render_dub_request_async
    from .errors import MCPVideoError

    try:
        if request is None and project_root is None:
            return _result(_invoke("sound-voice-batch", plan=plan))
        if plan is not None:
            raise MCPVideoError("caption request and synthetic plan modes conflict", error_type="validation_error")
        return _result(await render_dub_request_async(request, project_root))
    except SoundContractError as exc:
        raise MCPVideoError(str(exc), error_type=exc.error_type, code=exc.code) from exc


@mcp.tool()
@_safe_tool
async def sound_mix_render(request: dict[str, Any] | None = None, project_root: str | None = None) -> dict[str, Any]:
    """Assemble supplied WAVs into a new ZIP; omit both arguments for a labelled demo."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound.public.mix_job import render_mix_request_async
    from .errors import MCPVideoError

    try:
        if request is None and project_root is None:
            return _result(_invoke("sound-mix-render"))
        return _result(await render_mix_request_async(request, project_root))
    except SoundContractError as exc:
        raise MCPVideoError(str(exc), error_type=exc.error_type, code=exc.code) from exc


@mcp.tool()
@_safe_tool
async def sound_master_render(request: dict[str, Any], project_root: str) -> dict[str, Any]:
    """Retain a two-pass master only after measuring final audio against its policy."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound.public.master_job import render_master_request_async
    from .errors import MCPVideoError

    try:
        return _result(await render_master_request_async(request, project_root))
    except SoundContractError as exc:
        raise MCPVideoError(str(exc), error_type=exc.error_type, code=exc.code) from exc


@mcp.tool()
@_safe_tool
async def sound_qa_loudness(request: dict[str, Any] | None = None, project_root: str | None = None) -> dict[str, Any]:
    """Measure hashed local audio against its policy; omit inputs for a labelled demo."""
    from kinocut_sound._errors import SoundContractError
    from kinocut_sound.public.loudness_request import inspect_loudness_async
    from .errors import MCPVideoError

    try:
        return _result(await inspect_loudness_async(request=request, project_root=project_root))
    except SoundContractError as exc:
        raise MCPVideoError(str(exc), error_type=exc.error_type, code=exc.code) from exc


@mcp.tool()
@_safe_tool
def sound_qa_asr(
    script_hashes: list[str] | None = None,
    audio_duration_seconds: float = 1.0,
) -> dict[str, Any]:
    """Run the local fake ASR verification port against script hashes."""
    return _result(
        _invoke(
            "sound-qa-asr",
            script_hashes=script_hashes,
            audio_duration_seconds=audio_duration_seconds,
        )
    )
