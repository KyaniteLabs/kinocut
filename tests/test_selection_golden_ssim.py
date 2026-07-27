from __future__ import annotations

from pathlib import Path

from kinocut.ffmpeg_helpers import _run_ffmpeg
from kinocut.product.selection_evidence import measure_golden_render_ssim


def test_example_selection_golden_render_meets_ssim_without_byte_identity(tmp_path: Path) -> None:
    golden = tmp_path / "golden.mp4"
    candidate = tmp_path / "candidate.mp4"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=30:d=2",
            "-c:v",
            "libx264",
            "-crf",
            "12",
            "-pix_fmt",
            "yuv420p",
            str(golden),
        ]
    )
    _run_ffmpeg(
        [
            "-i",
            str(golden),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(candidate),
        ]
    )

    receipt = measure_golden_render_ssim(
        str(candidate),
        str(golden),
        selection_record_id="sha256:" + "a" * 64,
        selection_example_ids=("approved-learning",),
        threshold=0.98,
    )

    assert receipt.passed
    assert receipt.ssim >= receipt.threshold
    assert receipt.byte_identical is False
    assert receipt.candidate_sha256 != receipt.golden_sha256
    assert receipt.ffmpeg_version
