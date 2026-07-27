"""Golden-render evidence for example-influenced moment selections."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kinocut.defaults import DEFAULT_GOLDEN_RENDER_SSIM_THRESHOLD
from kinocut.contracts._common import ValueObject
from kinocut.errors import ProcessingError, ValidationError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path
from kinocut.workflow._versions import ffmpeg_version

_SSIM_ALL = re.compile(r"\bAll:([0-9]+(?:\.[0-9]+)?)")


class GoldenRenderSSIMReceipt(ValueObject):
    selection_record_id: str
    selection_example_ids: tuple[str, ...]
    candidate_sha256: str
    golden_sha256: str
    ssim: float
    threshold: float
    passed: bool
    byte_identical: bool
    ffmpeg_version: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def measure_golden_render_ssim(
    candidate_path: str,
    golden_path: str,
    *,
    selection_record_id: str,
    selection_example_ids: tuple[str, ...],
    threshold: float = DEFAULT_GOLDEN_RENDER_SSIM_THRESHOLD,
) -> GoldenRenderSSIMReceipt:
    """Compare decoded frames and report threshold evidence without byte-identity claims."""

    if not 0.0 <= threshold <= 1.0:
        raise ValidationError("threshold", "must be between zero and one")
    if not selection_example_ids:
        raise ValidationError("selection_example_ids", "at least one approved example is required")
    candidate = Path(_validate_input_path(candidate_path))
    golden = Path(_validate_input_path(golden_path))
    result = _run_ffmpeg(["-i", str(candidate), "-i", str(golden), "-lavfi", "ssim", "-f", "null", "-"])
    matches = _SSIM_ALL.findall(result.stderr)
    if not matches:
        raise ProcessingError("ffmpeg ssim", result.returncode, "SSIM summary was not produced")
    score = float(matches[-1])
    candidate_digest = _sha256(candidate)
    golden_digest = _sha256(golden)
    return GoldenRenderSSIMReceipt(
        selection_record_id=selection_record_id,
        selection_example_ids=tuple(dict.fromkeys(selection_example_ids)),
        candidate_sha256=candidate_digest,
        golden_sha256=golden_digest,
        ssim=score,
        threshold=threshold,
        passed=score >= threshold,
        byte_identical=candidate_digest == golden_digest,
        ffmpeg_version=ffmpeg_version(),
    )


__all__ = ["GoldenRenderSSIMReceipt", "measure_golden_render_ssim"]
