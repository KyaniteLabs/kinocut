"""PUSHING CREATION-compatible MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_project_create(slug: str, output_dir: str | None = None) -> dict[str, Any]:
    """Scaffold a cinematic video project with style, storyboard, and refs folders.

    Args:
        slug: Project slug using lowercase letters, numbers, hyphens, or underscores.
        output_dir: Base directory for the projects/ folder. Defaults to the current working directory.
    """
    from .creation_engine import create_video_project

    return _result(create_video_project(slug, output_dir=output_dir))


@mcp.tool()
@_safe_tool
def style_pack_read(path: str) -> dict[str, Any]:
    """Read STYLE_ and NEG_ blocks from a style.md file or project directory.

    Args:
        path: Absolute path to style.md or to a project directory containing style.md.
    """
    from .creation_engine import read_style_pack

    return _result(read_style_pack(path))


@mcp.tool()
@_safe_tool
def storyboard_read(path: str) -> dict[str, Any]:
    """Read a PUSHING CREATION storyboard table from storyboard.md or a project directory.

    Args:
        path: Absolute path to storyboard.md or to a project directory containing storyboard.md.
    """
    from .creation_engine import read_storyboard

    return _result(read_storyboard(path))


@mcp.tool()
@_safe_tool
def shot_prompt_render(project_path: str, shot: str) -> dict[str, Any]:
    """Expand one storyboard shot into prompt and negative_prompt strings.

    Args:
        project_path: Absolute path to a project directory containing style.md and storyboard.md.
        shot: Shot id or 1-based row number from storyboard.md.
    """
    from .creation_engine import render_shot_prompt

    return _result(render_shot_prompt(project_path, shot))
