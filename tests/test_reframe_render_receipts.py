from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from kinocut.ffmpeg_helpers import _run_ffmpeg
from kinocut.visual_intelligence import (
    CameraMotion,
    CropBudget,
    CropTarget,
    FrameEvidence,
    NormalizedBox,
    SourceVideo,
    SpeakerTurn,
    SubjectObservation,
    plan_subject_aware_reframe,
    plan_visual_analysis,
    render_reframe_plan,
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path, positions: tuple[int, int]) -> None:
    boxes = (
        f"drawbox=x={positions[0]}:y=90:w=60:h=180:color=red:t=fill,"
        f"drawbox=x={positions[1]}:y=90:w=60:h=180:color=blue:t=fill"
    )
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=10:d=4",
            "-vf",
            boxes,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _plan(source: Path, positions: tuple[int, int]):
    frames = tuple(
        FrameEvidence(
            timestamp_seconds=index / 10,
            subjects=tuple(
                SubjectObservation(
                    subject_id=subject_id,
                    box=NormalizedBox(x=x / 640, y=0.25, width=60 / 640, height=0.5),
                    confidence=0.99 if subject_id == "speaker-a" else 0.80,
                )
                for subject_id, x in zip(("speaker-a", "speaker-b"), positions, strict=True)
            ),
            camera_motion=CameraMotion(dx=0, dy=0, rotation_degrees=0, confidence=1),
        )
        for index in range(40)
    )
    analysis = plan_visual_analysis(
        source=SourceVideo(sha256=_sha256(source), width=640, height=360, duration_seconds=4),
        frames=frames,
        primary_subject_id="speaker-a",
        ambiguity_confidence_delta=0.05,
    )
    turns = tuple(
        SpeakerTurn(
            subject_id="speaker-a" if second % 2 == 0 else "speaker-b",
            start_seconds=second,
            end_seconds=second + 1,
            confidence=1,
        )
        for second in range(4)
    )
    return plan_subject_aware_reframe(
        analysis=analysis,
        targets=(CropTarget(target_id="portrait", aspect_width=9, aspect_height=16, output_width=180, output_height=320),),
        crop_budget=CropBudget(max_subject_loss=0.05, max_source_crop_fraction=0.7),
        max_center_step=1,
        speaker_turns=turns,
    )


def _color_centroid_x(path: Path, active_red: bool) -> float | None:
    image = Image.open(path).convert("RGB")
    points = []
    for y in range(image.height):
        for x in range(image.width):
            red, _green, blue = image.getpixel((x, y))
            if (red > 140 and red > blue * 2) if active_red else (blue > 140 and blue > red * 2):
                points.append(x)
    return sum(points) / len(points) if points else None


@pytest.mark.parametrize("positions", ((50, 500), (110, 470)))
def test_rendered_speaker_fixture_keeps_active_face_centroid_safe_and_receipts_ffmpeg(
    tmp_path: Path,
    positions: tuple[int, int],
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "portrait.mp4"
    frames = tmp_path / "frames"
    frames.mkdir()
    _source(source, positions)
    receipt = render_reframe_plan(str(source), str(output), _plan(source, positions), "portrait")
    _run_ffmpeg(["-i", str(output), "-vf", "fps=10", str(frames / "%03d.png")])

    samples = sorted(frames.glob("*.png"))
    safe = 0
    for index, frame in enumerate(samples):
        centroid = _color_centroid_x(frame, active_red=(index // 10) % 2 == 0)
        safe += centroid is not None and 0.15 * 180 <= centroid <= 0.85 * 180

    assert len(samples) == 40
    assert safe / len(samples) >= 0.95
    assert receipt.ffmpeg_version
    assert receipt.output_sha256 == _sha256(output)
    assert receipt.sample_count == 40
