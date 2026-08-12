#!/usr/bin/env python3
"""Build deterministic G004 multi-second phone-frame fixtures for product honesty.

Does not invent human-shot media. Produces synthetic but real media files that
exercise multi-shot + 9:16 phone-frame paths for watching/shorts gates.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def make_phone_frame(out: Path, *, seconds: float = 12.0) -> None:
    """9:16 synthetic multi-scene clip (>= multi-second for G004 acceptance)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    # three colored segments concatenated into one phone-frame master
    segs = []
    for i, color in enumerate(("red", "green", "blue")):
        seg = out.parent / f"_seg_{i}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=1080x1920:d={seconds / 3:.2f}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={440 + i * 40}:duration={seconds / 3:.2f}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(seg),
            ]
        )
        segs.append(seg)
    lst = out.parent / "_concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            str(out),
        ]
    )
    for s in segs:
        s.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-dir",
        default="tests/fixtures/g004",
        help="Output directory for fixtures",
    )
    p.add_argument("--seconds", type=float, default=12.0)
    args = p.parse_args()
    if not shutil.which("ffmpeg"):
        print("ffmpeg required", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    phone = out_dir / f"phone_frame_{int(args.seconds)}s.mp4"
    make_phone_frame(phone, seconds=args.seconds)
    manifest = {
        "artifact_kind": "g004_fixture_pack",
        "fixtures": [
            {
                "id": phone.stem,
                "path": str(phone.as_posix()),
                "aspect": "9:16",
                "duration_seconds_target": args.seconds,
                "multi_shot": True,
                "synthetic": True,
            }
        ],
        "notes": "Synthetic product fixtures for watching/shorts honesty — not human-captured media.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
