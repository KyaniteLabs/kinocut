"""kino init — local project scaffolding (TE.10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def init_project(
    path: str,
    *,
    name: str | None = None,
    with_cutfile: bool = True,
) -> dict[str, Any]:
    """Create a minimal Kinocut project directory (idempotent on empty dirs)."""
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    slug = name or root.name
    media = root / "media"
    out = root / "out"
    receipts = root / "receipts"
    for d in (media, out, receipts):
        d.mkdir(exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {slug}\n\nKinocut project scaffold.\n\n- `media/` inputs\n- `out/` renders\n- `receipts/` job receipts\n",
            encoding="utf-8",
        )
    cutfile_path = None
    if with_cutfile:
        cf = root / "cutfile.yaml"
        if not cf.exists():
            cf.write_text(
                f'name: "{slug}"\nversion: 1\nsources: []\nops: []\n',
                encoding="utf-8",
            )
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
