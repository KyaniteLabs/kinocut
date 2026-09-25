"""Append-only receipt writer for the compat-matrix harness (COMPAT-MATRIX-SPEC).

Receipt format of record: the per-step JSON schema in
docs/local-first/COMPAT-MATRIX-SPEC.md, extended for the skeleton era with
outcome "not_wired" / fail_reason "not_wired" (a step whose driver lane is a
later build order is reported honestly instead of being silently skipped or
counted as a driver failure). Receipts are append-only: this module only ever
opens steps.jsonl / runs.jsonl in append mode and refuses to rewrite history.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

STEPS_FILENAME = "steps.jsonl"
RUNS_FILENAME = "runs.jsonl"

REQUIRED_FIELDS = (
    "tier",
    "model",
    "endpoint",
    "step",
    "attempt",
    "tool_call",
    "tool_args_valid",
    "outcome",
    "fail_reason",
    "tokens",
    "latency_ms",
    "artifact_sha256",
    "ground_truth_diff",
    "cloud_keys_present",
    "timestamp_utc",
)

OUTCOMES = ("pass", "fail", "not_wired")  # "not_wired" = skeleton-era extension
FAIL_REASONS = (
    "schema_violation",
    "wrong_arg",
    "loop_exhausted",
    "timeout",
    "render_error",
    "not_wired",  # skeleton-era extension
    None,
)
TOKEN_FIELDS = ("prompt", "completion", "manifest_bytes")
GROUND_TRUTH_DIFFS = ("identical", "acceptable", "divergent", "not_applicable")

# Offline-cloud-free assertion (spec: "cloud_keys_present is part of every
# receipt"). Env-var NAME patterns only — values are never read, logged, or
# stored. KINOCUT_VISION_* is the one optional cloud credential the inventory
# flagged; any presence here marks the run cloud-keyed.
CLOUD_KEY_ENV_PATTERNS = (
    re.compile(r"^KINOCUT_VISION_[A-Z_]*KEY$"),
    re.compile(r"^(OPENAI|ANTHROPIC|GOOGLE|GEMINI|DEEPSEEK|OPENROUTER|GROQ|MISTRAL|"
               r"TOGETHER|REPLICATE|ELEVENLABS|FIREWORKS|PERPLEXITY|XAI)_API_KEY$"),
    re.compile(r"^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AZURE_OPENAI_API_KEY)$"),
)


def detect_cloud_keys(environ: dict[str, str] | None = None) -> bool:
    """True if any known cloud-credential env var NAME is set in this process."""
    env = environ if environ is not None else dict(os.environ)
    return any(p.match(name) for name in env for p in CLOUD_KEY_ENV_PATTERNS)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    """Return a list of schema violations (empty list = valid)."""
    errors: list[str] = []
    for field_name in REQUIRED_FIELDS:
        if field_name not in receipt:
            errors.append(f"missing field: {field_name}")
    if errors:
        return errors
    if receipt["outcome"] not in OUTCOMES:
        errors.append(f"bad outcome: {receipt['outcome']!r}")
    if receipt["fail_reason"] not in FAIL_REASONS:
        errors.append(f"bad fail_reason: {receipt['fail_reason']!r}")
    if receipt["outcome"] == "fail" and receipt["fail_reason"] is None:
        errors.append("fail outcome requires a non-null fail_reason (honest receipts law)")
    if receipt["outcome"] not in ("fail", "not_wired") and receipt["fail_reason"] is not None:
        errors.append("non-fail outcome requires fail_reason null")
    if receipt["outcome"] == "not_wired" and receipt["fail_reason"] != "not_wired":
        errors.append("not_wired outcome must pair with fail_reason not_wired")
    if receipt["ground_truth_diff"] not in GROUND_TRUTH_DIFFS:
        errors.append(f"bad ground_truth_diff: {receipt['ground_truth_diff']!r}")
    tokens = receipt["tokens"]
    if not isinstance(tokens, dict) or any(k not in tokens for k in TOKEN_FIELDS):
        errors.append(f"tokens must carry {TOKEN_FIELDS}")
    if not isinstance(receipt["attempt"], int) or receipt["attempt"] < 1:
        errors.append("attempt must be an integer >= 1")
    if not isinstance(receipt["cloud_keys_present"], bool):
        errors.append("cloud_keys_present must be boolean")
    if receipt["artifact_sha256"] is not None and not re.fullmatch(
        r"[0-9a-f]{64}", str(receipt["artifact_sha256"])
    ):
        errors.append("artifact_sha256 must be a lowercase sha256 hex or null")
    return errors


class ReceiptWriter:
    """Append-only JSONL receipt store for one run directory."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.steps_path = self.run_dir / STEPS_FILENAME
        self.runs_path = self.run_dir / RUNS_FILENAME

    def _append(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:  # append-only, never rewrite
            fh.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    def write_step(self, receipt: dict[str, Any]) -> dict[str, Any]:
        errors = validate_receipt(receipt)
        if errors:
            raise ValueError("invalid step receipt: " + "; ".join(errors))
        self._append(self.steps_path, receipt)
        return receipt

    def write_run(self, run_receipt: dict[str, Any]) -> dict[str, Any]:
        self._append(self.runs_path, run_receipt)
        return run_receipt

    def read_steps(self) -> list[dict[str, Any]]:
        if not self.steps_path.exists():
            return []
        return [json.loads(line) for line in self.steps_path.read_text().splitlines() if line]
