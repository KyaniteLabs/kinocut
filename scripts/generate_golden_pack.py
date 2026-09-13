#!/usr/bin/env python3
"""Build a shareable pack only from a current, strictly valid golden-path run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT

if __package__:
    from scripts.golden_path import GoldenPathError, _bounded, _commit_identity, _validate_artifacts
else:  # pragma: no cover - exercised by the documented script invocation
    from golden_path import GoldenPathError, _bounded, _commit_identity, _validate_artifacts

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "demo" / "golden-pack"
ARTIFACTS = PACK / "artifacts"
SOURCE_OUTPUT = ROOT / "workflows" / "05-confidence-baseline" / "output"
CLAIMS = ROOT / "docs" / "public_claims.json"
COPY_NAMES = (
    "video_receipt.json",
    "quality.json",
    "release_checkpoint.json",
    "final_clip.mp4",
    "source.mp4",
    "01_trimmed.mp4",
    "02_vertical.mp4",
    "03_captioned.mp4",
    "04_normalized.mp4",
)


def _validated_receipt() -> dict[str, Any]:
    receipt_path = SOURCE_OUTPUT / "video_receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoldenPathError(f"invalid reusable video receipt: {_bounded(exc)}") from exc
    run_id = receipt.get("run_id") if isinstance(receipt, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise GoldenPathError("reusable video receipt has no run_id")
    validated, _, _ = _validate_artifacts(SOURCE_OUTPUT, run_id, _commit_identity())
    return validated


def _sanitize_path(value: object) -> object:
    return Path(value).name if isinstance(value, str) and value else value


def _packed_receipt(receipt: dict[str, Any], generated_at: str, published: object) -> dict[str, Any]:
    packed = json.loads(json.dumps(receipt))
    for call in packed.get("tool_calls") or []:
        if isinstance(call, dict):
            call["output"] = _sanitize_path(call.get("output"))
    source = packed.get("source_media")
    if isinstance(source, dict):
        source["path"] = _sanitize_path(source.get("path"))
    artifacts = packed.get("review_artifacts")
    if isinstance(artifacts, dict):
        for key in ("final_video", "quality_report", "release_checkpoint", "thumbnail"):
            artifacts[key] = _sanitize_path(artifacts.get(key))
        frames = artifacts.get("storyboard")
        if isinstance(frames, list):
            artifacts["storyboard"] = [_sanitize_path(frame) for frame in frames]
    packed["evidence_class"] = "synthetic_fixture"
    packed["pack"] = {
        "generated_at": generated_at,
        "kinocut_published_version": published,
        "generator": "scripts/generate_golden_pack.py",
    }
    return packed


def _copy_artifacts(destination: Path) -> list[str]:
    copied: list[str] = []
    destination.mkdir()
    for name in COPY_NAMES:
        source = SOURCE_OUTPUT / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied.append(name)
    checkpoint = SOURCE_OUTPUT / "checkpoint"
    if checkpoint.is_dir():
        shutil.copytree(checkpoint, destination / "checkpoint")
        copied.append("checkpoint/")
    return copied


def _manifest(copied: list[str], generated_at: str, published: object) -> str:
    files = "\n".join(f"- `{name}`" for name in sorted(copied))
    return f"""# Golden pack artifacts

Generated: {generated_at}
Published package claim: {published or "unknown"}
Evidence class: synthetic fixture; human review remains pending.

## Files

{files}

## How to regenerate

```bash
python scripts/golden_path.py
python scripts/generate_golden_pack.py --skip-run
```

Media files (*.mp4, images) are gitignored. Commit JSON proofs only when intentionally curated.
"""


def _sample(packed: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "run_id",
        "candidate",
        "user_intent",
        "source_media",
        "edits_applied",
        "tool_calls",
        "quality",
        "review_artifacts",
        "human_review",
        "known_limitations",
        "evidence_class",
        "pack",
    )
    return {key: packed.get(key) for key in keys}


def _publish(stage_artifacts: Path, stage_sample: Path) -> None:
    PACK.parent.mkdir(parents=True, exist_ok=True)
    pack_existed = PACK.exists()
    PACK.mkdir(parents=True, exist_ok=True)
    backup_root = stage_artifacts.parent / "backup"
    backup_root.mkdir()
    prior_artifacts = backup_root / "artifacts"
    prior_sample = backup_root / "sample.json"
    sample_path = PACK / "sample_video_receipt.json"
    artifacts_backed_up = False
    sample_backed_up = False
    artifacts_promoted = False
    sample_promoted = False
    try:
        if ARTIFACTS.exists():
            os.replace(ARTIFACTS, prior_artifacts)
            artifacts_backed_up = True
        if sample_path.exists():
            os.replace(sample_path, prior_sample)
            sample_backed_up = True
        os.replace(stage_artifacts, ARTIFACTS)
        artifacts_promoted = True
        os.replace(stage_sample, sample_path)
        sample_promoted = True
    except OSError:
        if artifacts_promoted and ARTIFACTS.exists():
            shutil.rmtree(ARTIFACTS)
        if sample_promoted and sample_path.exists():
            sample_path.unlink()
        if artifacts_backed_up:
            os.replace(prior_artifacts, ARTIFACTS)
        if sample_backed_up:
            os.replace(prior_sample, sample_path)
        if not pack_existed and not any(PACK.iterdir()):
            PACK.rmdir()
        raise


def _build_pack(receipt: dict[str, Any]) -> None:
    claims = json.loads(CLAIMS.read_text(encoding="utf-8")) if CLAIMS.is_file() else {}
    published = claims.get("published_version") if isinstance(claims, dict) else None
    generated_at = datetime.now(UTC).isoformat()
    PACK.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".kinocut-golden-pack-", dir=PACK.parent) as temporary:
        stage_root = Path(temporary)
        stage_artifacts = stage_root / "artifacts"
        copied = _copy_artifacts(stage_artifacts)
        packed = _packed_receipt(receipt, generated_at, published)
        (stage_artifacts / "video_receipt.json").write_text(
            json.dumps(packed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (stage_artifacts / "MANIFEST.md").write_text(_manifest(copied, generated_at, published), encoding="utf-8")
        stage_sample = stage_root / "sample.json"
        stage_sample.write_text(json.dumps(_sample(packed), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _publish(stage_artifacts, stage_sample)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-run", action="store_true", help="Reuse existing strictly validated baseline output")
    args = parser.parse_args(argv)
    if not args.skip_run:
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "golden_path.py")],
                timeout=DEFAULT_FFMPEG_TIMEOUT,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"FAIL: golden path did not complete: {_bounded(exc)}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            return result.returncode
    try:
        _build_pack(_validated_receipt())
    except (GoldenPathError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"FAIL: {_bounded(exc)}", file=sys.stderr)
        return 1
    print(f"Pack written to {ARTIFACTS}")
    print(f"Shareable sample receipt: {PACK / 'sample_video_receipt.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
