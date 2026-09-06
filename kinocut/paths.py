"""Path generation helpers for Kinocut."""

from __future__ import annotations

import os


def _auto_output(input_path: str, suffix: str = "edited", ext: str | None = None) -> str:
    base, original_ext = os.path.splitext(input_path)
    ext = ext or original_ext or ".mp4"
    # Sanitize colons in the base path — they break FFmpeg filter syntax.
    # Split the drive off first: on Windows the leading "C:" is a drive
    # separator, and replacing it turns an absolute path into a relative one.
    drive, tail = os.path.splitdrive(base)
    safe_base = drive + tail.replace(":", "_")
    output = f"{safe_base}_{suffix}{ext}"
    # Prevent overwriting the input file
    if output == input_path:
        base_out, ext_out = os.path.splitext(output)
        output = f"{base_out}_2{ext_out}"
    return output


def _auto_output_dir(input_path: str, suffix: str = "output") -> str:
    base, _ = os.path.splitext(input_path)
    drive, tail = os.path.splitdrive(base)
    safe_base = drive + tail.replace(":", "_")
    return f"{safe_base}_{suffix}"
