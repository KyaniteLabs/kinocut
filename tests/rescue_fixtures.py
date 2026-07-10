"""Deterministic FFmpeg fixtures for rescue-pipeline acceptance tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg fixture generation failed: {result.stderr.strip()}")


def make_rescue_fixture(
    tmp_path: Path,
    *,
    rotation: int = 0,
    brightness: float = 0.0,
    volume_db: float = 0.0,
    noise: bool = False,
    vfr: bool = False,
    drift_ms: int = 0,
    container: str = "mp4",
    hostile_name: bool = False,
) -> Path:
    """Create one three-second synthetic video with only the requested defects."""
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("rotation must be 0, 90, 180, or 270")
    if container not in {"mp4", "mov", "webm"}:
        raise ValueError("container must be mp4, mov, or webm")

    root = Path(tmp_path) / "rescue-fixtures"
    root.mkdir(parents=True, exist_ok=True)
    stem = "resume [final] #1 - video" if hostile_name else "rescue-source"
    output = root / f"{stem}.{container}"
    encoded = output if rotation == 0 else root / f".{stem}.encoded.{container}"

    video_filters = []
    if brightness:
        video_filters.append(f"eq=brightness={brightness}")
    if vfr:
        video_filters.append("setpts=N/(30*TB)+mod(N\\,2)*0.01/TB")
    video_chain = ",".join(video_filters) if video_filters else "null"

    audio_inputs = [
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
    ]
    if noise:
        audio_inputs.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anoisesrc=color=white:amplitude=0.015:sample_rate=48000:duration=3",
            ]
        )
        audio_chain = "[1:a][2:a]amix=inputs=2:duration=first"
    else:
        audio_chain = "[1:a]anull"
    if volume_db:
        audio_chain += f",volume={volume_db}dB"
    if drift_ms:
        audio_chain += f",adelay={drift_ms}:all=1"

    video_codec = "libvpx-vp9" if container == "webm" else "libx264"
    audio_codec = "libopus" if container == "webm" else "aac"
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=30:duration=3",
        *audio_inputs,
        "-filter_complex",
        f"[0:v]{video_chain}[v];{audio_chain}[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        "3",
        "-c:v",
        video_codec,
        "-threads",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        audio_codec,
        "-ar",
        "48000",
    ]
    if container != "webm":
        command.extend(["-preset", "ultrafast", "-crf", "23"])
    else:
        command.extend(["-deadline", "realtime", "-cpu-used", "8", "-crf", "35", "-b:v", "0"])
    if vfr:
        command.extend(["-fps_mode", "vfr"])
    command.append(str(encoded))
    _run(command)

    if rotation:
        _run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(encoded),
                "-map",
                "0",
                "-c",
                "copy",
                "-metadata:s:v:0",
                f"rotate={rotation}",
                str(output),
            ]
        )
        encoded.unlink()
    return output


def make_corrupt_fixture(tmp_path: Path) -> Path:
    """Write deterministic bytes that cannot be decoded as media."""
    path = Path(tmp_path) / "rescue-fixtures" / "corrupt.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-media-container\x00mcp-video-rescue\n")
    return path


def make_long_unicode_fixture(tmp_path: Path) -> Path:
    """Create valid media behind a long Unicode and punctuation-heavy name."""
    source = make_rescue_fixture(tmp_path)
    target = source.with_name(f"resume-final-cafe-{'x' * 80}-\u6d4b\u8bd5 [1].mp4")
    shutil.copy2(source, target)
    return target


def make_unsupported_codec_fixture(tmp_path: Path) -> Path:
    """Write a deterministic unknown-codec input for fail-closed tests."""
    path = Path(tmp_path) / "rescue-fixtures" / "unknown-codec.mcpv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MCPV\x01unknown-video-codec\x00\x00\x00\x03")
    return path
