#!/usr/bin/env python3
"""Build a shareable Kinocut demo pack under demo/golden-pack/artifacts/.

Runs the golden path (unless --skip-run), then copies receipt/quality/checkpoint
JSON and a MANIFEST.md into the pack directory. Large media is copied when
present but remains gitignored (*.mp4).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "demo" / "golden-pack"
ARTIFACTS = PACK / "artifacts"
SOURCE_OUTPUT = ROOT / "workflows" / "05-confidence-baseline" / "output"
CLAIMS = ROOT / "docs" / "public_claims.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-run", action="store_true", help="Reuse existing baseline output")
    args = parser.parse_args()

    if not args.skip_run:
        gp = subprocess.run([sys.executable, str(ROOT / "scripts" / "golden_path.py")])
        if gp.returncode != 0:
            return gp.returncode

    if not (SOURCE_OUTPUT / "video_receipt.json").is_file():
        print("FAIL: no baseline output; run without --skip-run", file=sys.stderr)
        return 1

    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS)
    ARTIFACTS.mkdir(parents=True)

    copied: list[str] = []
    for name in (
        "video_receipt.json",
        "quality.json",
        "release_checkpoint.json",
        "final_clip.mp4",
        "source.mp4",
        "01_trimmed.mp4",
        "02_vertical.mp4",
        "03_captioned.mp4",
        "04_normalized.mp4",
    ):
        src = SOURCE_OUTPUT / name
        if src.is_file():
            shutil.copy2(src, ARTIFACTS / name)
            copied.append(name)

    # Checkpoint directory (thumbnail/storyboard) when present
    ck = SOURCE_OUTPUT / "checkpoint"
    if ck.is_dir():
        dest = ARTIFACTS / "checkpoint"
        shutil.copytree(ck, dest)
        copied.append("checkpoint/")

    claims = json.loads(CLAIMS.read_text(encoding="utf-8")) if CLAIMS.is_file() else {}
    receipt = json.loads((ARTIFACTS / "video_receipt.json").read_text(encoding="utf-8"))
    # Normalize absolute paths in the packed receipt for sharing
    packed_receipt = json.loads(json.dumps(receipt))
    for call in packed_receipt.get("tool_calls") or []:
        out = call.get("output")
        if isinstance(out, str) and out:
            call["output"] = Path(out).name
    if isinstance(packed_receipt.get("source_media"), dict):
        path = packed_receipt["source_media"].get("path")
        if path:
            packed_receipt["source_media"]["path"] = Path(path).name
    ra = packed_receipt.get("review_artifacts") or {}
    for key in ("final_video", "quality_report", "release_checkpoint", "thumbnail"):
        if isinstance(ra.get(key), str) and ra[key]:
            ra[key] = Path(ra[key]).name
    frames = ra.get("storyboard")
    if isinstance(frames, list):
        ra["storyboard"] = [Path(f).name if isinstance(f, str) else f for f in frames]
    packed_receipt["review_artifacts"] = ra
    packed_receipt["pack"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kinocut_published_version": claims.get("published_version"),
        "generator": "scripts/generate_golden_pack.py",
    }
    (ARTIFACTS / "video_receipt.json").write_text(
        json.dumps(packed_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest = f"""# Golden pack artifacts

Generated: {packed_receipt["pack"]["generated_at"]}
Published package claim: {claims.get("published_version", "unknown")}

## Files

{chr(10).join(f"- `{name}`" for name in sorted(copied))}

## How to regenerate

```bash
python scripts/golden_path.py
python scripts/generate_golden_pack.py --skip-run
```

Media files (*.mp4, images) are gitignored. Commit JSON proofs when intentionally curated.
"""
    (ARTIFACTS / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    # Always keep a committed-friendly sample receipt at pack root (no large media refs required)
    sample = {
        "user_intent": packed_receipt.get("user_intent"),
        "edits_applied": packed_receipt.get("edits_applied"),
        "tool_calls": packed_receipt.get("tool_calls"),
        "quality": packed_receipt.get("quality"),
        "human_review": packed_receipt.get("human_review"),
        "known_limitations": packed_receipt.get("known_limitations"),
        "pack": packed_receipt.get("pack"),
    }
    (PACK / "sample_video_receipt.json").write_text(
        json.dumps(sample, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Pack written to {ARTIFACTS}")
    print(f"Shareable sample receipt: {PACK / 'sample_video_receipt.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
