"""Still I/O helpers — dependency checks, path validation, load/save."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_location, _validate_input_path
from ..hashing import file_sha256 as file_sha256


class ReceiptStatus(StrEnum):
    """Outcome of a still/plate receipt: planned by a dry run, or finished."""

    PLANNED = "planned"
    OK = "ok"
    GATE_FAILED = "gate_failed"


STILL_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})


def require_still_deps() -> None:
    """Require Pillow + NumPy for still-plate pixel work."""
    missing: list[str] = []
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        missing.append("pillow")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        raise MCPVideoError(
            'Still/plate tools require image extras (pillow, numpy). Install with: pip install "kinocut[image]==2.0.1"',
            error_type="dependency_error",
            code="missing_still_plate_deps",
            suggested_action={
                "auto_fix": False,
                "description": 'Run: pip install "kinocut[image]==2.0.1"',
            },
        )


def validate_still_path(path: str | Path, *, must_exist: bool = True) -> Path:
    """Validate a still image path."""
    p = Path(path).expanduser()
    if must_exist:
        _validate_input_path(str(p))
    if p.suffix.lower() not in STILL_EXTENSIONS:
        raise MCPVideoError(
            f"Unsupported still format. Supported: {', '.join(sorted(STILL_EXTENSIONS))}",
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
    """Save a float RGB array (0..1) as PNG/JPEG by extension.

    Goes through the shared output validation and anchored publication like
    every other media output: an existing file needs overwrite consent, and a
    destination that aliases one of this operation's inputs is refused.
    """
    require_still_deps()
    import numpy as np
    from PIL import Image

    from ..ffmpeg_helpers import _atomic_output, _validate_output_path

    out = Path(path)
    target = _validate_output_path(str(out))
    clipped = np.clip(arr, 0.0, 1.0)
    u8 = (clipped * 255.0 + 0.5).astype("uint8")
    with _atomic_output(target) as staged:
        Image.fromarray(u8, mode="RGB").save(staged)
    return Path(target).resolve()


def write_receipt(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a JSON receipt through the anchored artifact publisher.

    Strips absolute home-rooted paths from string values. An existing receipt
    is only replaced with overwrite consent, never silently.
    """
    from ..ffmpeg_helpers import _atomic_artifact, _validate_artifact_path

    out = Path(path)
    target = _validate_artifact_path(str(out))
    sanitized = _sanitize_receipt(payload)
    with _atomic_artifact(target) as staged:
        Path(staged).write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Path(target).resolve()


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


def confined_leaf(directory: Path, name: str) -> Path:
    """Return a direct, non-symlink child on either supported path syntax."""
    if not name or name in {".", ".."} or PureWindowsPath(name).name != name or Path(name).name != name:
        raise MCPVideoError(
            "Expected a plain output filename", error_type="validation_error", code="invalid_output_path"
        )
    leaf = directory / name
    _validate_artifact_location(str(leaf), "Output filename")
    return leaf


def ensure_output_dir(path: str | Path) -> Path:
    """Create and return an output directory path."""
    out = Path(path).expanduser()
    _validate_artifact_location(str(out), "Output directory")
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()
