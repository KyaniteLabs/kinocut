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
def sound_voice_batch(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render a local deterministic voice batch from a SoundPlan (or a minimal plan)."""
    return _result(_invoke("sound-voice-batch", plan=plan))


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
def sound_qa_loudness() -> dict[str, Any]:
    """Measure loudness against the default delivery policy on synthetic audio."""
    return _result(_invoke("sound-qa-loudness"))


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
