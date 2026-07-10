"""PUSHING CREATION-style project, style-pack, and storyboard helpers."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
import re
import shutil
from typing import Any

from .errors import MCPVideoError

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_BLOCK_RE = re.compile(r"^##\s+((?:STYLE|NEG)_[A-Z0-9_]+)\s*$")
_STORYBOARD_COLUMNS = (
    "shot",
    "provider",
    "model",
    "camera",
    "lens",
    "aspect",
    "action",
    "refs",
    "style",
    "neg",
    "mode",
    "duration",
)


def _creation_error(message: str, code: str = "invalid_parameter") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _validate_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise _creation_error("Invalid slug: use lowercase letters, numbers, hyphens, or underscores")
    return slug


def _resolve_dir(path: str | None) -> Path:
    base = Path(path or ".").expanduser().resolve()
    if base.exists() and not base.is_dir():
        raise _creation_error(f"Output directory is not a directory: {base}")
    return base


def _template_path(name: str) -> Path:
    return Path(str(resources.files("kinocut.creation_templates").joinpath(name)))


def _copy_template(name: str, destination: Path) -> None:
    shutil.copyfile(_template_path(name), destination)


def create_video_project(slug: str, output_dir: str | None = None) -> dict[str, Any]:
    """Scaffold a PUSHING CREATION-compatible video project."""
    slug = _validate_slug(slug)
    project = _resolve_dir(output_dir) / "projects" / slug
    if project.exists():
        raise _creation_error(f"Project already exists: {project}", code="project_exists")

    refs = project / "refs"
    refs.mkdir(parents=True)
    _copy_template("style.md", project / "style.md")
    _copy_template("storyboard.md", project / "storyboard.md")
    (refs / ".gitkeep").write_text("")

    return {
        "project_path": str(project),
        "files": [str(project / "style.md"), str(project / "storyboard.md"), str(refs)],
        "next_steps": [
            "Drop reference stills, plates, or mood frames into refs/.",
            "Customize style.md STYLE_ and NEG_ blocks for the project's visual voice.",
            "Replace the storyboard example rows with the project's own shot list.",
        ],
    }


def _read_text_file(path: str, filename: str | None = None) -> tuple[Path, str]:
    candidate = Path(path).expanduser()
    if candidate.is_dir() and filename:
        candidate = candidate / filename
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise _creation_error(f"File not found: {resolved}", code="not_found")
    return resolved, resolved.read_text()


def read_style_pack(path: str) -> dict[str, Any]:
    """Parse STYLE_ and NEG_ blocks from a style.md file or project directory."""
    resolved, text = _read_text_file(path, "style.md")
    blocks: list[dict[str, str]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_name is None:
            return
        body = " ".join(line.strip() for line in current_lines if line.strip())
        blocks.append({"name": current_name, "type": current_name.split("_", 1)[0], "body": body})

    for line in text.splitlines():
        match = _BLOCK_RE.match(line.strip())
        if match:
            flush()
            current_name = match.group(1)
            current_lines = []
            continue
        if current_name is not None and not line.lstrip().startswith("<!--"):
            current_lines.append(line)
    flush()

    style_blocks = [block for block in blocks if block["type"] == "STYLE"]
    negative_blocks = [block for block in blocks if block["type"] == "NEG"]
    return {
        "style_path": str(resolved),
        "block_count": len(blocks),
        "blocks": blocks,
        "style_blocks": style_blocks,
        "negative_blocks": negative_blocks,
    }


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell.replace(":", "").strip()) <= {"-"} for cell in cells)


def _split_refs(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]


def _split_blocks(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;+]", value) if part.strip()]


def read_storyboard(path: str) -> dict[str, Any]:
    """Parse a PUSHING CREATION storyboard markdown table."""
    resolved, text = _read_text_file(path, "storyboard.md")
    rows: list[dict[str, Any]] = []
    header_seen = False

    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _split_table_row(line)
        lower_cells = [cell.lower() for cell in cells]
        if lower_cells == list(_STORYBOARD_COLUMNS):
            header_seen = True
            continue
        if not header_seen or _is_separator_row(cells):
            continue
        if len(cells) != len(_STORYBOARD_COLUMNS):
            continue
        row = dict(zip(_STORYBOARD_COLUMNS, cells, strict=True))
        row["refs"] = _split_refs(row["refs"])
        row["style"] = _split_blocks(row["style"])
        row["neg"] = _split_blocks(row["neg"])
        rows.append(row)

    return {"storyboard_path": str(resolved), "shot_count": len(rows), "shots": rows}


def _find_shot(storyboard: dict[str, Any], shot: str | int) -> dict[str, Any]:
    shots = storyboard["shots"]
    if isinstance(shot, int) or str(shot).isdigit():
        index = int(shot) - 1
        if 0 <= index < len(shots):
            return shots[index]
    for row in shots:
        if row["shot"] == str(shot):
            return row
    raise _creation_error(f"Shot not found: {shot}", code="not_found")


def render_shot_prompt(project_path: str, shot: str | int) -> dict[str, Any]:
    """Expand storyboard style references into a provider-ready shot prompt."""
    project = Path(project_path).expanduser().resolve()
    style_pack = read_style_pack(str(project))
    storyboard = read_storyboard(str(project))
    row = _find_shot(storyboard, shot)
    block_map = {block["name"]: block["body"] for block in style_pack["blocks"]}

    missing = [name for name in [*row["style"], *row["neg"]] if name and name not in block_map]
    if missing:
        raise _creation_error(f"Referenced style blocks not found: {', '.join(missing)}", code="missing_style_block")

    style_parts = [block_map[name] for name in row["style"] if name]
    negative_parts = [block_map[name] for name in row["neg"] if name]
    prompt_parts = [row["action"], *style_parts]

    return {
        "shot": row["shot"],
        "provider": row["provider"],
        "model": row["model"],
        "mode": row["mode"],
        "duration": row["duration"],
        "aspect": row["aspect"],
        "refs": row["refs"],
        "style_blocks": row["style"],
        "negative_blocks": row["neg"],
        "prompt": "\n\n".join(part for part in prompt_parts if part),
        "negative_prompt": ", ".join(part for part in negative_parts if part),
    }
