#!/usr/bin/env python3
"""Run and verify the receipt-backed Kinocut confidence baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_FFMPEG_TIMEOUT
from kinocut.errors import ProcessingError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW_DIR = REPO_ROOT / "workflows" / "05-confidence-baseline"
BENCHMARK_OUTPUT = REPO_ROOT / "workflows" / "benchmarks" / "output"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _path_exists(value: Any) -> bool:
    if not value:
        return False
    return Path(str(value)).expanduser().exists()


def _check_receipt(receipt: dict[str, Any]) -> list[dict[str, str]]:
    checks = [
        ("receipt_has_intent", bool(receipt.get("user_intent"))),
        ("quality_passed", receipt.get("quality", {}).get("all_passed") is True),
        ("quality_score_present", receipt.get("quality", {}).get("overall_score") is not None),
        ("final_video_exists", _path_exists(receipt.get("review_artifacts", {}).get("final_video"))),
        ("quality_report_exists", _path_exists(receipt.get("review_artifacts", {}).get("quality_report"))),
        ("release_checkpoint_exists", _path_exists(receipt.get("review_artifacts", {}).get("release_checkpoint"))),
        ("thumbnail_exists", _path_exists(receipt.get("review_artifacts", {}).get("thumbnail"))),
        ("storyboard_has_frames", len(receipt.get("review_artifacts", {}).get("storyboard", [])) >= 4),
        ("human_review_required", receipt.get("human_review", {}).get("required") is True),
        ("human_review_pending", receipt.get("human_review", {}).get("status") == "pending"),
    ]
    return [{"name": name, "status": "pass" if passed else "fail"} for name, passed in checks]


def _run_workflow(workflow_dir: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, str(workflow_dir / "workflow.py")],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            str(workflow_dir / "workflow.py"),
            124,
            f"Workflow {workflow_dir} timed out after {DEFAULT_FFMPEG_TIMEOUT}s",
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-dir", type=Path, default=DEFAULT_WORKFLOW_DIR)
    parser.add_argument(
        "--skip-run", action="store_true", help="Validate the existing receipt without rerunning workflow."
    )
    args = parser.parse_args()

    workflow_dir = args.workflow_dir.expanduser().resolve()
    receipt_path = workflow_dir / "output" / "video_receipt.json"
    BENCHMARK_OUTPUT.mkdir(parents=True, exist_ok=True)

    run_result: subprocess.CompletedProcess[str] | None = None
    if not args.skip_run:
        run_result = _run_workflow(workflow_dir)

    if not receipt_path.exists():
        report = {
            "benchmark": "confidence-baseline",
            "passed": False,
            "receipt_path": str(receipt_path),
            "checks": [{"name": "receipt_exists", "status": "fail"}],
            "workflow_returncode": run_result.returncode if run_result else None,
            "workflow_stdout_tail": (run_result.stdout[-4000:] if run_result else ""),
            "workflow_stderr_tail": (run_result.stderr[-4000:] if run_result else ""),
        }
        _write_report(report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    receipt = _load_json(receipt_path)
    checks = [{"name": "receipt_exists", "status": "pass"}, *_check_receipt(receipt)]
    if not args.skip_run:
        workflow_completed = run_result is not None and run_result.returncode == 0
        checks.insert(1, {"name": "workflow_completed", "status": "pass" if workflow_completed else "fail"})
    passed = all(check["status"] == "pass" for check in checks)
    report = {
        "benchmark": "confidence-baseline",
        "passed": passed,
        "receipt_path": str(receipt_path),
        "checks": checks,
        "quality": receipt.get("quality", {}),
        "human_review": receipt.get("human_review", {}),
        "workflow_returncode": run_result.returncode if run_result else None,
    }
    _write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


def _write_report(report: dict[str, Any]) -> None:
    output_path = BENCHMARK_OUTPUT / "confidence-benchmark-latest.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
