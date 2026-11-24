"""Locate render and snapshot output artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def _snapshot_pngs(project: Path, before: set[Path]) -> list[str]:
    """Only frames Hyperframes wrote during this call; stale frames are never passed off as new."""
    snapshot_dir = project / "snapshots"
    if not snapshot_dir.is_dir():
        return []
    created = set(snapshot_dir.glob("*.png")) - before
    return [str(path) for path in sorted(created)]


def _default_render_output(project_path: str, output_format: str | None) -> str:
    """Return a format-appropriate default render artifact path inside the project.

    The default used to be ``./out`` relative to the server's working directory,
    keyed by project basename: two projects with the same name overwrote each
    other's renders and a read-only working directory broke the render before it
    started. Keeping the artifact next to the composition (where Hyperframes
    already writes ``snapshots/``) namespaces it by project and stays writable.
    """
    project = Path(project_path)
    out_dir = project / "renders"
    os.makedirs(out_dir, exist_ok=True)
    name = project.name
    match output_format:
        case "png-sequence":
            return os.path.join(str(out_dir), f"{name}_frames")
        case "webm" | "mov" | "mp4":
            return os.path.join(str(out_dir), f"{name}.{output_format}")
        case _:
            return os.path.join(str(out_dir), f"{name}.mp4")


def _render_output_exists(output_path: str, output_format: str | None) -> bool:
    """Return true when the expected Hyperframes artifact exists."""
    if output_format == "png-sequence":
        output_dir = Path(output_path)
        return output_dir.is_dir() and any(output_dir.glob("*.png"))
    return os.path.isfile(output_path)
