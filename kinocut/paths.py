"""Path generation helpers for mcp-video."""

from __future__ import annotations

import os


def _auto_output(input_path: str, suffix: str = "edited", ext: str | None = None) -> str:
    base, original_ext = os.path.splitext(input_path)
    ext = ext or original_ext or ".mp4"
    # Sanitize colons in base path — they break FFmpeg filter syntax
    # and are problematic on Windows
    safe_base = base.replace(":", "_")
    output = f"{safe_base}_{suffix}{ext}"
    # Prevent overwriting the input file
    if output == input_path:
        base_out, ext_out = os.path.splitext(output)
        output = f"{base_out}_2{ext_out}"
    return output


def _auto_output_dir(input_path: str, suffix: str = "output") -> str:
    base, _ = os.path.splitext(input_path)
    safe_base = base.replace(":", "_")
    return f"{safe_base}_{suffix}"
