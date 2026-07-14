#!/usr/bin/env python3
"""Kinocut golden path — 60-second first-run proof.

Runs:
  1. kino doctor (required checks must pass)
  2. confidence baseline workflow (trim → vertical → caption → normalize → export → quality → receipt)
  3. success criteria checks on generated artifacts

Exit 0 only when the path is green. Media stays local under workflows/05-confidence-baseline/output/
(and is gitignored).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "05-confidence-baseline" / "workflow.py"
OUTPUT = ROOT / "workflows" / "05-confidence-baseline" / "output"
REQUIRED_ARTIFACTS = (
    "final_clip.mp4",
    "video_receipt.json",
    "quality.json",
    "release_checkpoint.json",
)


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def _fail(msg: str, *, detail: str = "") -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)
    return 1


def main() -> int:
    print("=" * 60)
    print("Kinocut golden path")
    print("=" * 60)

    # Prefer the active interpreter so local editable installs work.
    py = sys.executable

    print("\n[1/3] Doctor (required dependencies)...")
    doctor = _run([py, "-m", "kinocut", "doctor", "--json"])
    if doctor.returncode != 0:
        return _fail("kino doctor exited non-zero", detail=doctor.stderr or doctor.stdout)
    try:
        report = json.loads(doctor.stdout)
    except json.JSONDecodeError:
        # Text mode fallback if JSON not on stdout
        text = _run([py, "-m", "kinocut", "doctor"])
        if text.returncode != 0:
            return _fail("kino doctor failed", detail=text.stderr or text.stdout)
        print(text.stdout)
        report = {"summary": {"required_ok": True}}
    summary = report.get("summary") or {}
    if summary.get("required_ok") is False:
        missing = summary.get("missing_required") or []
        return _fail(f"required doctor checks failed: {missing}", detail=doctor.stdout)
    print("   OK required checks passed")

    print("\n[2/3] Confidence baseline workflow...")
    if not WORKFLOW.is_file():
        return _fail(f"missing workflow script: {WORKFLOW}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    wf = _run([py, str(WORKFLOW)], cwd=WORKFLOW.parent)
    if wf.returncode != 0:
        return _fail(
            "confidence baseline failed",
            detail=(wf.stdout or "") + "\n" + (wf.stderr or ""),
        )
    print(wf.stdout[-2000:] if wf.stdout else "")
    print("   OK workflow completed")

    print("\n[3/3] Success criteria...")
    missing = [name for name in REQUIRED_ARTIFACTS if not (OUTPUT / name).is_file()]
    if missing:
        return _fail(f"missing artifacts: {missing}")

    receipt = json.loads((OUTPUT / "video_receipt.json").read_text(encoding="utf-8"))
    quality = json.loads((OUTPUT / "quality.json").read_text(encoding="utf-8"))
    if not receipt.get("tool_calls"):
        return _fail("video_receipt.json has no tool_calls")
    if receipt.get("human_review", {}).get("status") != "pending":
        return _fail("expected human_review.status == pending")
    final = Path(receipt.get("review_artifacts", {}).get("final_video") or OUTPUT / "final_clip.mp4")
    if not final.is_file():
        return _fail(f"final video missing: {final}")

    print("   OK artifacts present")
    print("   OK receipt has tool_calls and pending human review")
    if quality.get("all_passed") is False:
        print("   NOTE quality.all_passed is false — still a valid proof; inspect quality.json")
    else:
        print(f"   OK quality.all_passed={quality.get('all_passed')} score={quality.get('overall_score')}")

    print("\n" + "=" * 60)
    print("GOLDEN PATH GREEN")
    print(f"  final:   {final}")
    print(f"  receipt: {OUTPUT / 'video_receipt.json'}")
    print(f"  quality: {OUTPUT / 'quality.json'}")
    print("  Human visual/audio review is still required before publish.")
    print("=" * 60)
    print("\nNext: python scripts/generate_golden_pack.py  # optional shareable pack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
