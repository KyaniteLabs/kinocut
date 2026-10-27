#!/usr/bin/env python3
"""Fail if built release artifacts contain forbidden repo surface paths
or omit the license text Apache-2.0 §4(a) requires to accompany a distribution."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_SUBSTRINGS = (
    "/.github/",
    "/.git/",
    "/.playwright-mcp/",
    "/.pytest_cache/",
    "/.ruff_cache/",
    "/.stitch/",
    "/__pycache__/",
    "/demo/",
    "/docs/",
    "/dogfood_artifacts/",
    "/explainer-video/",
    "/examples/",
    "/manual/",
    "/out/",
)

FORBIDDEN_SUFFIXES = (
    "/.coverage",
    "/.git",
    "/index.html",
    "/og-social-preview.png",
    "/uv.lock",
    ".mp3",
    ".mp4",
    ".mov",
    ".wav",
    ".webm",
    "/test_comprehensive.py",
    "/test_real_video.py",
)


def find_offenders(artifact: Path) -> list[str]:
    names: list[str]
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as zf:
            names = zf.namelist()
    elif artifact.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(artifact, "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
    else:
        raise ValueError(f"Unsupported artifact type: {artifact}")

    offenders = []
    for name in names:
        normalized = f"/{name.lstrip('/')}"
        if any(fragment in normalized for fragment in FORBIDDEN_SUBSTRINGS) or any(
            normalized.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES
        ):
            offenders.append(name)
    return offenders


def ships_license_text(artifact: Path) -> bool:
    """Apache-2.0 §4(a): wheels carry the license in <pkg>.dist-info/licenses/,
    sdists at the top level of the archive root."""
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as zf:
            names = zf.namelist()
    elif artifact.suffixes[-2:] == [".tar", ".gz"]:
        with tarfile.open(artifact, "r:gz") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
    else:
        raise ValueError(f"Unsupported artifact type: {artifact}")
    if any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        return True
    return bool(names) and f"{names[0].split('/', 1)[0]}/LICENSE" in names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", nargs="?", default="dist")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    artifacts = sorted(artifact_dir.glob("*.whl")) + sorted(artifact_dir.glob("*.tar.gz"))
    if not artifacts:
        raise SystemExit(f"No wheel or sdist artifacts found in {artifact_dir}")

    failed = False
    for artifact in artifacts:
        offenders = find_offenders(artifact)
        unlicensed = not ships_license_text(artifact)
        if offenders or unlicensed:
            failed = True
            print(
                f"{artifact.name}: forbidden contents detected"
                if offenders
                else f"{artifact.name}: license text missing"
            )
            for offender in offenders:
                print(f"- {offender}")
            if unlicensed:
                print("- LICENSE (Apache-2.0 §4(a) requires the license copy to accompany the distribution)")
        else:
            print(f"{artifact.name}: clean")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
