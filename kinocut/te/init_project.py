"""kino init — local project scaffolding (TE.10)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _atomic_artifact, _open_staged_writer, _validate_output_path


def _render_cutfile_yaml(slug: str) -> str:
    """Serialize the starter cutfile without requiring optional PyYAML."""
    return f"name: {json.dumps(slug)}\nversion: 1\nsources: []\nops: []\n"


def _write_scaffold_file(target: Path, content: str) -> None:
    """Create a scaffold file if absent, refusing symlinks (including dangling ones)."""
    if os.path.islink(target):
        raise MCPVideoError(
            "Project scaffold path resolves through a symlink",
            error_type="validation_error",
            code="unsafe_path",
        )
    if os.path.lexists(target):
        return
    with _atomic_artifact(str(target)) as staged, _open_staged_writer(staged) as stream:
        stream.write(content.encode("utf-8"))


def init_project(
    path: str,
    *,
    name: str | None = None,
    with_cutfile: bool = True,
) -> dict[str, Any]:
    """Create a minimal Kinocut project directory (idempotent on empty dirs)."""
    expanded = str(Path(path).expanduser())
    safe_path = _validate_output_path(expanded)
    root = Path(safe_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    slug = name or root.name
    media = root / "media"
    out = root / "out"
    receipts = root / "receipts"
    for d in (media, out, receipts):
        if os.path.islink(d):
            raise MCPVideoError(
                "Project scaffold directory resolves through a symlink",
                error_type="validation_error",
                code="unsafe_path",
            )
        d.mkdir(exist_ok=True)
    readme = root / "README.md"
    _write_scaffold_file(
        readme,
        f"# {slug}\n\nKinocut project scaffold.\n\n- `media/` inputs\n- `out/` renders\n- `receipts/` job receipts\n",
    )
    cutfile_path = None
    if with_cutfile:
        cf = root / "cutfile.yaml"
        _write_scaffold_file(cf, _render_cutfile_yaml(slug))
        cutfile_path = str(cf)
    return {
        "artifact_kind": "project_init",
        "path": str(root),
        "name": slug,
        "media_dir": str(media),
        "out_dir": str(out),
        "receipts_dir": str(receipts),
        "cutfile": cutfile_path,
    }
