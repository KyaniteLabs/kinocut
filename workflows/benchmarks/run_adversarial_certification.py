#!/usr/bin/env python3
"""Run a small adversarial readiness certification for Kinocut workflows."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from kinocut import Client
from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "workflows" / "benchmarks" / "output" / "adversarial-certification"
REPORT_PATH = REPO_ROOT / "workflows" / "benchmarks" / "output" / "adversarial-certification-latest.json"


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(" ".join(cmd), 124, f"FFmpeg timed out after {DEFAULT_FFMPEG_TIMEOUT}s") from exc
    except subprocess.CalledProcessError as exc:
        raise ProcessingError(" ".join(cmd), exc.returncode, exc.stderr or "") from exc


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _make_video(path: Path, *, volume: float = 1.0, rate: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1280x720:rate={rate}",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-filter:a",
            f"volume={volume}",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )


def _case_quiet_audio(client: Client) -> dict[str, Any]:
    path = OUTPUT_DIR / "very quiet audio.mp4"
    _make_video(path, volume=0.02)
    quality = client.quality_check(str(path))
    recommendations = quality.get("recommendations", []) if isinstance(quality, dict) else quality.recommendations
    passed = any(
        "quiet" in recommendation.lower() or "lufs" in recommendation.lower() for recommendation in recommendations
    )
    return {
        "case": "very_quiet_audio",
        "passed": passed,
        "artifact": str(path),
        "expectation": "quality recommendations should flag quiet audio",
        "observed": recommendations,
    }


def _case_long_filename(client: Client) -> dict[str, Any]:
    path = OUTPUT_DIR / "long filename with spaces for path handling.mp4"
    _make_video(path)
    checkpoint = client.release_checkpoint(
        str(path), output_dir=str(OUTPUT_DIR / "long filename checkpoint"), min_score=50
    )
    storyboard = _field(checkpoint, "storyboard", {})
    frames = _field(storyboard, "frames", [])
    thumbnail = _field(checkpoint, "thumbnail")
    return {
        "case": "long_filename_with_spaces",
        "passed": bool(thumbnail) and len(frames) >= 4,
        "artifact": str(path),
        "expectation": "release checkpoint should handle spaces in media paths",
        "observed": {"frame_count": len(frames)},
    }


def _case_weird_frame_rate(client: Client) -> dict[str, Any]:
    path = OUTPUT_DIR / "weird-rate-17fps.mp4"
    _make_video(path, rate=17)
    resized = client.resize(str(path), aspect_ratio="9:16", output=str(OUTPUT_DIR / "weird-rate-17fps-vertical.mp4"))
    info = client.info(resized.output_path)
    return {
        "case": "weird_frame_rate_resize",
        "passed": info.width == 1080 and info.height == 1920,
        "artifact": resized.output_path,
        "expectation": "resize should produce a vertical 9:16 output",
        "observed": {"width": info.width, "height": info.height, "duration": info.duration},
    }


def _case_corrupted_input(client: Client) -> dict[str, Any]:
    path = OUTPUT_DIR / "corrupted-input.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real media file")
    try:
        client.info(str(path))
    except InputFileError as exc:
        return {
            "case": "corrupted_input",
            "passed": True,
            "artifact": str(path),
            "expectation": "corrupted input should fail clearly",
            "observed": str(exc),
        }
    except MCPVideoError as exc:
        return {
            "case": "corrupted_input",
            "passed": False,
            "artifact": str(path),
            "expectation": "corrupted input should fail with InputFileError",
            "observed": str(exc),
        }
    return {
        "case": "corrupted_input",
        "passed": False,
        "artifact": str(path),
        "expectation": "corrupted input should fail clearly",
        "observed": "client.info unexpectedly accepted corrupted input",
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = Client()
    cases = [
        _case_quiet_audio(client),
        _case_long_filename(client),
        _case_weird_frame_rate(client),
        _case_corrupted_input(client),
    ]
    report = {
        "certification": "agentic-video-certify-local",
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
