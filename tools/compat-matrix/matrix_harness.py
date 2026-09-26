#!/usr/bin/env python3
"""Compat-matrix harness — skeleton (COMPAT-MATRIX-SPEC build order 1).

Build order 1 scope: MCP client + endpoint config + receipt writer, with the
CLI ground-truth mode first and NO model. This driver runs the pinned
canonical scenario (ingest -> trim -> caption -> repurpose -> quality-gate ->
receipt) in two modes:

- ``cli-ground-truth`` (default, deterministic, this build): every wired step
  runs once via the ``kino`` CLI to produce the ground-truth artifact that
  later model-driven runs are compared against (spec: "deterministic fallback
  path"). Caption is reported ``not_wired`` in the skeleton era (local-whisper
  ground truth is a mini/G2 model lane — compute law), never faked.
- ``agent`` (build order 2+): refuses to run — T1 wiring is a later burst.

Laws baked in (spec Constraints): zero spend (DIR-0010) — this mode performs
no model calls at all; no cloud keys — asserted per receipt; receipts
append-only; guardrail tools consumed via their public CLI, never bypassed.

Usage:
  python tools/compat-matrix/matrix_harness.py [--mode cli-ground-truth]
      [--run-root docs/local-first/matrix-runs] [--kino-python .venv/bin/python]
  python tools/compat-matrix/matrix_harness.py --mcp-handshake   # prove the MCP client
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from mcp_client import MCPStdioClient  # noqa: E402
from receipt_writer import ReceiptWriter, detect_cloud_keys, utc_now_iso  # noqa: E402

HARNESS_VERSION = "0.1.0-skeleton"
STEP_ORDER = ("ingest", "trim", "caption", "repurpose", "quality-gate", "receipt")
CLI_STEP_TIMEOUT_S = 120.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sanitize_artifact_text(text: str, root: Path) -> str:
    """Strip the absolute ``root`` prefix from paths embedded in artifact text.

    Workspace-relative-paths law (tests/test_receipt_privacy.py): committed
    plan artifacts and receipts must never carry absolute home-dir paths.
    kino CLI outputs embed absolute paths (they resolve outputs against cwd);
    this relativizes them at record time so the run directory is committable
    as-is. Content is otherwise untouched; JSON stays valid (plain prefix
    replacement inside JSON string values cannot break escaping because the
    prefix contains no JSON metacharacters).
    """
    prefix = str(root.resolve())
    text = text.replace(prefix + "/", "").replace(prefix, ".")
    return text


def sanitize_artifact_tree(directory: Path, root: Path) -> list[Path]:
    """Sanitize every ``*.json`` under ``directory``; returns changed paths.

    Applied to CLI-written artifact dirs (ingest project, repurpose plans)
    BEFORE receipt hashes are computed, so steps.jsonl always pins the
    sanitized (committable) content.
    """
    changed: list[Path] = []
    if not directory.exists():
        return changed
    for path in sorted(directory.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        sanitized = sanitize_artifact_text(text, root)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")
            changed.append(path)
    return changed


class GroundTruthRun:
    """One cli-ground-truth pass over the pinned scenario."""

    def __init__(self, scenario: dict[str, Any], endpoints: dict[str, Any], kino_cmd: list[str], run_dir: Path):
        self.scenario = scenario
        self.endpoints = endpoints
        self.kino_cmd = kino_cmd
        self.run_dir = run_dir
        self.writer = ReceiptWriter(run_dir)
        self.artifacts_dir = run_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.clip = REPO_ROOT / scenario["clip"]["path"]
        self.tier_cfg = endpoints["tiers"]["cli-ground-truth"]

    # -- plumbing ------------------------------------------------------
    def _cli(self, args: list[str]) -> tuple[int, str, str, float]:
        """Run one kino CLI command; returns (rc, stdout, stderr, latency_ms)."""
        started = time.monotonic()
        proc = subprocess.run(  # noqa: S603 - repo-owned kino CLI, list-literal argv
            [*self.kino_cmd, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=CLI_STEP_TIMEOUT_S,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        return proc.returncode, proc.stdout, proc.stderr, latency_ms

    def _dump(self, name: str, content: str) -> Path:
        path = self.artifacts_dir / name
        path.write_text(sanitize_artifact_text(content, REPO_ROOT), encoding="utf-8")
        return path

    def _receipt(
        self,
        step: str,
        tool_call: str,
        outcome: str,
        fail_reason: str | None,
        latency_ms: int,
        artifact_sha256: str | None,
    ) -> dict[str, Any]:
        return {
            "tier": "cli-ground-truth",
            "model": None,
            "endpoint": None,
            "step": step,
            "attempt": 1,
            "tool_call": tool_call,
            "tool_args_valid": outcome != "fail" or fail_reason != "wrong_arg",
            "outcome": outcome,
            "fail_reason": fail_reason,
            "tokens": {"prompt": 0, "completion": 0, "manifest_bytes": 0},
            "latency_ms": latency_ms,
            "artifact_sha256": artifact_sha256,
            # ground-truth lane: this run IS the reference; diff vs itself = identical
            "ground_truth_diff": "identical" if outcome == "pass" else "not_applicable",
            "cloud_keys_present": detect_cloud_keys(),
            "timestamp_utc": utc_now_iso(),
            "harness_version": HARNESS_VERSION,
        }

    # -- steps ---------------------------------------------------------
    def step_ingest(self) -> dict[str, Any]:
        cfg = self.scenario["steps"]["ingest"]
        project_dir = self.artifacts_dir / "ingest-project"
        rc, _out, _err, latency = self._cli(
            [
                "video-ingest",
                str(project_dir),
                str(self.clip),
                "--usage-rights-status",
                cfg["usage_rights_status"],
            ]
        )
        artifacts = sorted(p for p in project_dir.rglob("*") if p.is_file()) if project_dir.exists() else []
        sanitize_artifact_tree(project_dir, REPO_ROOT)  # privacy law: hash sanitized content
        if rc == 0 and artifacts:
            payload = "\n".join(f"{sha256_file(p)}  {p.name}" for p in artifacts)
            manifest = self._dump("ingest-manifest-sha256.txt", payload + "\n")
            return self._receipt("ingest", cfg["tool"], "pass", None, latency, sha256_file(manifest))
        return self._receipt("ingest", cfg["tool"], "fail", "render_error", latency, None)

    def step_trim(self) -> dict[str, Any]:
        cfg = self.scenario["steps"]["trim"]
        out_path = self.artifacts_dir / "trim-0.5s.mp4"
        rc, _out, _err, latency = self._cli(
            [
                "trim",
                str(self.clip),
                "-s",
                str(cfg["start_s"]),
                "-d",
                str(cfg["duration_s"]),
                "-o",
                str(out_path),
            ]
        )
        if rc == 0 and out_path.exists():
            return self._receipt("trim", cfg["tool"], "pass", None, latency, sha256_file(out_path))
        return self._receipt("trim", cfg["tool"], "fail", "render_error", latency, None)

    def step_caption(self) -> dict[str, Any]:
        cfg = self.scenario["steps"]["caption"]
        if cfg.get("mode") != "transcribe-local":
            return self._receipt("caption", cfg["tool"], "not_wired", "not_wired", 0, None)
        rc, out, _err, latency = self._cli(["video-ai-transcribe", str(self.clip), "--format", "json"])
        srt = next((ln for ln in out.splitlines() if ln.strip().endswith(".srt")), None)
        if rc == 0 and srt:
            srt_path = Path(srt.strip())
            return self._receipt(
                "caption", cfg["tool"], "pass", None, latency, sha256_file(srt_path) if srt_path.exists() else None
            )
        return self._receipt("caption", cfg["tool"], "fail", "render_error", latency, None)

    def step_repurpose(self) -> dict[str, Any]:
        cfg = self.scenario["steps"]["repurpose"]
        out_dir = self.artifacts_dir / "repurpose"
        rc, _out, _err, latency = self._cli(
            [
                "repurpose-plan",
                str(self.clip),
                "-o",
                str(out_dir),
                "--platforms",
                *cfg["platforms"],
            ]
        )
        plans = sorted(out_dir.rglob("*.json")) if out_dir.exists() else []
        sanitize_artifact_tree(out_dir, REPO_ROOT)  # privacy law: hash sanitized content
        if rc == 0 and plans:
            manifest = self._dump(
                "repurpose-plan-sha256.txt", "\n".join(f"{sha256_file(p)}  {p.name}" for p in plans) + "\n"
            )
            return self._receipt("repurpose", cfg["tool"], "pass", None, latency, sha256_file(manifest))
        return self._receipt("repurpose", cfg["tool"], "fail", "render_error", latency, None)

    def step_quality_gate(self) -> dict[str, Any]:
        cfg = self.scenario["steps"]["quality-gate"]
        subject = self.artifacts_dir / "trim-0.5s.mp4"
        args = ["video-quality-check", "--format", "json"]
        if cfg.get("fail_on_warning"):
            args.append("--fail-on-warning")
        args.append(str(subject if subject.exists() else self.clip))
        rc, out, _err, latency = self._cli(args)
        dump = self._dump("quality-gate.json", out if out.strip() else "{}")
        if rc == 0:
            return self._receipt("quality-gate", cfg["tool"], "pass", None, latency, sha256_file(dump))
        return self._receipt("quality-gate", cfg["tool"], "fail", "render_error", latency, sha256_file(dump))

    def step_receipt(self) -> dict[str, Any]:
        started = time.monotonic()
        payload = self.writer.steps_path.read_bytes() if self.writer.steps_path.exists() else b""
        digest = sha256_bytes(payload)
        latency = int((time.monotonic() - started) * 1000)
        return self._receipt("receipt", "receipt-writer", "pass", None, latency, digest)

    # -- run -----------------------------------------------------------
    def run(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        for step_fn in (
            self.step_ingest,
            self.step_trim,
            self.step_caption,
            self.step_repurpose,
            self.step_quality_gate,
        ):
            receipt = step_fn()
            steps.append(self.writer.write_step(receipt))
            print(
                f"[{receipt['step']:>12}] {receipt['outcome']}"
                + (f" ({receipt['fail_reason']})" if receipt["fail_reason"] else "")
            )
        receipt_step = self.writer.write_step(self.step_receipt())
        steps.append(receipt_step)
        print(f"[{'receipt':>12}] pass")

        wired = [s for s in steps if s["outcome"] != "not_wired"]
        run_receipt = {
            "run_id": f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-cli-ground-truth",
            "tier": "cli-ground-truth",
            "mode": "cli-ground-truth",
            "scenario_id": self.scenario["scenario_id"],
            "scenario_sha256": self.scenario["clip"]["sha256"],
            "steps_total": len(steps),
            "steps_pass": sum(1 for s in wired if s["outcome"] == "pass"),
            "steps_fail": sum(1 for s in wired if s["outcome"] == "fail"),
            "steps_not_wired": sum(1 for s in steps if s["outcome"] == "not_wired"),
            "wired_pass_all": all(s["outcome"] == "pass" for s in wired),
            "total_tokens": {"prompt": 0, "completion": 0, "manifest_bytes": 0},
            "total_latency_ms": sum(s["latency_ms"] for s in steps),
            "cloud_keys_present": detect_cloud_keys(),
            "harness_version": HARNESS_VERSION,
            "timestamp_utc": utc_now_iso(),
        }
        self.writer.write_run(run_receipt)
        return run_receipt


def mcp_handshake(kino_cmd: list[str]) -> int:
    """Prove the MCP client + measure the manifest (spec token accounting)."""
    with MCPStdioClient([*kino_cmd, "--mcp"], cwd=str(REPO_ROOT), timeout=90.0) as client:
        info = client.handshake()
    print(f"server: {info.server_name} v{info.server_version} (protocol {info.protocol_version})")
    print(f"tools: {info.tools_count}  manifest_bytes: {info.manifest_bytes}")
    return 0 if info.tools_count > 0 and info.manifest_bytes > 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="kinocut compat-matrix harness (skeleton)")
    parser.add_argument("--mode", choices=("cli-ground-truth", "agent"), default="cli-ground-truth")
    parser.add_argument("--scenario", default=str(HERE / "scenario.json"))
    parser.add_argument("--endpoints", default=str(HERE / "endpoints.json"))
    parser.add_argument("--run-root", default=str(REPO_ROOT / "docs/local-first/matrix-runs"))
    parser.add_argument("--kino-python", default=sys.executable)
    parser.add_argument(
        "--mcp-handshake", action="store_true", help="only prove the MCP client handshake + manifest accounting"
    )
    args = parser.parse_args(argv)

    kino_cmd = [args.kino_python, "-m", "kinocut"]
    if args.mcp_handshake:
        return mcp_handshake(kino_cmd)
    if args.mode == "agent":
        print(
            "agent mode is not wired: T1 wiring is COMPAT-MATRIX-SPEC build order 2 "
            "(engines endpoint, mini/gpu-host lane). Refusing to fake a model run."
        )
        return 2

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    endpoints = json.loads(Path(args.endpoints).read_text(encoding="utf-8"))

    clip = REPO_ROOT / scenario["clip"]["path"]
    if not clip.exists():
        print(f"scenario clip missing: {clip}", file=sys.stderr)
        return 2
    actual = sha256_file(clip)
    if actual != scenario["clip"]["sha256"]:
        print(f"scenario clip hash drift: expected {scenario['clip']['sha256']}, got {actual}", file=sys.stderr)
        return 2

    run_dir = Path(args.run_root) / f"{time.strftime('%Y-%m-%d', time.gmtime())}-cli-ground-truth"
    gt = GroundTruthRun(scenario, endpoints, kino_cmd, run_dir)
    run_receipt = gt.run()
    print(f"run dir: {run_dir}")
    print(
        f"verdict: wired_pass_all={run_receipt['wired_pass_all']} "
        f"(pass {run_receipt['steps_pass']}/{run_receipt['steps_pass'] + run_receipt['steps_fail']}"
        f" wired, {run_receipt['steps_not_wired']} not_wired)"
    )
    return 0 if run_receipt["wired_pass_all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
