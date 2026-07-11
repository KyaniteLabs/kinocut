#!/usr/bin/env python3
"""Deterministic current-tools demo for the Kinocut repurpose skill."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PLATFORMS = ("youtube-shorts", "instagram-reel")
DISPLAY_RECIPE = [
    ["kino", "info", "{fixture}"],
    ["kino", "repurpose-plan", "{fixture}", "--platforms", *PLATFORMS, "-o", "{package}"],
    ["kino", "repurpose", "{fixture}", "--platforms", *PLATFORMS, "-o", "{package}", "--min-score", "0"],
    ["kino", "video-quality-check", "{package}/youtube_shorts.mp4"],
]


def _format_command(parts: list[str], *, fixture: Path, package: Path) -> str:
    return " ".join(part.format(fixture=fixture, package=package) for part in parts)


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - demo commands are fixed Kinocut/FFmpeg argv lists.
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _kinocut_command(command: str, *args: str) -> list[str]:
    return [sys.executable, "-m", "kinocut", command, *args]


def _create_fixture(path: Path, *, cwd: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("FFmpeg is required for the deterministic demo fixture.")
    _run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        cwd=cwd,
    )


def _load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _verify_package(package: Path) -> None:
    manifest = _load_manifest(package / "repurpose_manifest.json")
    platforms = {variant["platform"]: variant for variant in manifest["variants"]}
    for platform in PLATFORMS:
        variant = platforms[platform]
        output = Path(variant["output_path"])
        if not output.is_file():
            raise SystemExit(f"Missing rendered output: {output}")
        if not Path(variant["thumbnail"]).is_file():
            raise SystemExit(f"Missing thumbnail for {platform}")
        if not Path(variant["storyboard"]["output_path"]).is_file():
            raise SystemExit(f"Missing storyboard for {platform}")
        checkpoint = variant.get("release_checkpoint", {})
        if not checkpoint.get("review_required"):
            raise SystemExit(f"Missing review gate for {platform}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out/repurpose-current-tools-demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    display_output_dir = Path(args.output_dir)
    output_dir = display_output_dir if display_output_dir.is_absolute() else root / display_output_dir
    fixture = output_dir / "fixtures" / "current-tools-source.mp4"
    package = output_dir / "package"
    display_fixture = display_output_dir / "fixtures" / "current-tools-source.mp4"
    display_package = display_output_dir / "package"

    if args.dry_run:
        print("# Deterministic fixture")
        print(
            "ffmpeg -y -f lavfi -i testsrc2=size=640x360:rate=30 "
            "-f lavfi -i sine=frequency=880:sample_rate=48000 -t 4 "
            "-c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "
            + str(display_fixture)
        )
        print("# Current Kinocut recipe")
        for command in DISPLAY_RECIPE:
            print(_format_command(command, fixture=display_fixture, package=display_package))
        return 0

    if package.exists():
        shutil.rmtree(package)
    _create_fixture(fixture, cwd=root)
    _run(_kinocut_command("info", str(fixture)), cwd=root)
    _run(_kinocut_command("repurpose-plan", str(fixture), "--platforms", *PLATFORMS, "-o", str(package)), cwd=root)
    _run(
        _kinocut_command("repurpose", str(fixture), "--platforms", *PLATFORMS, "-o", str(package), "--min-score", "0"),
        cwd=root,
    )
    _run(_kinocut_command("video-quality-check", str(package / "youtube_shorts.mp4")), cwd=root)
    _verify_package(package)
    print(json.dumps({"status": "ok", "fixture": str(fixture), "package": str(package)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
