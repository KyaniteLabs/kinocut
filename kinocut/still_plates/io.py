"""Still I/O helpers — dependency checks, path validation, load/save."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError

STILL_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})


def require_still_deps() -> None:
    """Require Pillow for still-plate pixel work."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError as exc:
        raise MCPVideoError(
            'Still/plate tools require image extras. Install with: pip install "kinocut[image]"',
            error_type="dependency_error",
            code="missing_still_plate_deps",
            suggested_action={
                "auto_fix": False,
                "description": 'Run: pip install "kinocut[image]"',
            },
        ) from exc


def validate_still_path(path: str | Path, *, must_exist: bool = True) -> Path:
    """Validate a still image path."""
    p = Path(path).expanduser()
    if must_exist and not p.is_file():
        raise MCPVideoError(
            f"Still not found: {path}",
            error_type="input_error",
            code="file_not_found",
        )
    if p.suffix.lower() not in STILL_EXTENSIONS:
        raise MCPVideoError(
            f"Unsupported still format: {p.suffix}. Supported: {', '.join(sorted(STILL_EXTENSIONS))}",
            error_type="validation_error",
            code="unsupported_still_format",
        )
    return p.resolve() if p.exists() else p


def load_rgb_array(path: str | Path):
    """Load a still as float RGB array in 0..1 range (H, W, 3)."""
    require_still_deps()
    import numpy as np
    from PIL import Image

    p = validate_still_path(path)
    with Image.open(p) as img:
        rgb = img.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
    return arr


def save_rgb_array(arr, path: str | Path) -> Path:
    """Save a float RGB array (0..1) as PNG/JPEG by extension."""
    require_still_deps()
    import numpy as np
    from PIL import Image

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(arr, 0.0, 1.0)
    u8 = (clipped * 255.0 + 0.5).astype("uint8")
    Image.fromarray(u8, mode="RGB").save(out)
    return out.resolve()


def file_sha256(path: str | Path) -> str:
    """Content hash for receipts."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_receipt(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a JSON receipt; strip absolute home-rooted paths from string values."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_receipt(payload)
    out.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out.resolve()


def _sanitize_receipt(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sanitize_receipt(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_receipt(v) for v in value]
    if isinstance(value, str):
        home = str(Path.home())
        if value.startswith(home + os.sep):
            return value.replace(home, "~", 1)
        return value
    return value


def ensure_output_dir(path: str | Path) -> Path:
    """Create and return an output directory path."""
    out = Path(path).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()
