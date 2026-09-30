"""Normalize measured SDR code units without transfer-function conversion."""

import json
import logging
import math
import re
from typing import Any

from .errors import MCPVideoError

logger = logging.getLogger(__name__)


def _normalized_signalstat(frame: dict[str, Any], tag: str, value: Any, *, difference: bool = False) -> float:
    """Map native sample units into 8-bit limited-range SDR code units.

    No transfer-function conversion or tone mapping occurs. Metadata omitted by
    older probes defaults to 8-bit/limited; yuvj formats imply full range.
    Difference images are amplitudes and must never receive a black offset.
    """
    pixel_format = frame.get("pix_fmt", "")
    if not isinstance(pixel_format, str):
        raise MCPVideoError("Invalid signalstats pixel format", error_type="analysis_error")
    depth_match = re.search(r"(?:p|gray)(\d+)(?:le|be)$", pixel_format)
    depth = int(depth_match.group(1)) if depth_match else 8
    number = float(value)
    if depth not in {8, 9, 10, 12, 14, 16} or not math.isfinite(number):
        raise MCPVideoError("Invalid signalstats depth or non-finite value", error_type="analysis_error")
    full_range = frame.get("color_range") in {"pc", "jpeg", "full"} or pixel_format.startswith("yuvj")
    component = tag.rsplit(".", 1)[-1]
    if not full_range:
        return number / (2 ** (depth - 8))
    full_scale = (2 ** depth) - 1
    if difference:
        return number * 219 / full_scale
    if component in {"UAVG", "VAVG"}:
        return 128 + (number - (2 ** (depth - 1))) * 224 / full_scale
    if component == "SATAVG":
        return number * 224 / full_scale
    return 16 + number * 219 / full_scale


def _signalstats_frames(stdout: str) -> list[dict[str, Any]]:
    """Read one analysis pass and warn once if decoded transfer is PQ/HLG."""
    frames = json.loads(stdout).get("frames", [])
    if any(frame.get("color_transfer") in {"smpte2084", "arib-std-b67"} for frame in frames):
        logger.warning("HDR transfer observed: SDR signalstats heuristics do not evaluate HDR delivery acceptance")
    return frames
