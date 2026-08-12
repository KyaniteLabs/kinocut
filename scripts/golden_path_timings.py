#!/usr/bin/env python3
"""WP-F golden-path timing harness (baseline scaffolding).

Default mode is cheap and fixture-backed:
  1. kino doctor --json
  2. kino --format json info <fixture>

Optional full mode times scripts/golden_path.py (FFmpeg confidence workflow).

Does NOT claim product optimization and does NOT bump public_claims.json.
Write measured rows into docs/status/golden-path-timings.md after a run.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "golden" / "workflow_final.mp4"
DEFAULT_RUNS = 5
STEP_TIMEOUT_S = 120
FULL_TIMEOUT_S = 600


@dataclass(frozen=True)
class StepStats:
    step: str
    runs: int
    ok_runs: int
    samples_s: list[float]
    p50_s: float | None
    p95_s: float | None
    mean_s: float | None
    min_s: float | None
    max_s: float | None


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # Nearest-rank linear interpolation (same idea as numpy percentile linear).
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _stats(step: str, samples: list[float], ok_runs: int) -> StepStats:
    sorted_s = sorted(samples)
    return StepStats(
        step=step,
        runs=len(samples),
        ok_runs=ok_runs,
        samples_s=[round(s, 4) for s in samples],
        p50_s=round(_percentile(sorted_s, 50) or 0.0, 4) if sorted_s else None,
        p95_s=round(_percentile(sorted_s, 95) or 0.0, 4) if sorted_s else None,
        mean_s=round(statistics.fmean(samples), 4) if samples else None,
        min_s=round(min(samples), 4) if samples else None,
        max_s=round(max(samples), 4) if samples else None,
    )


def _run_timed(cmd: list[str], *, timeout: int) -> tuple[float, int, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        elapsed = time.perf_counter() - t0
        detail = (proc.stderr or proc.stdout or "").strip()
        return elapsed, proc.returncode, detail[-500:] if detail else ""
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        return elapsed, 124, f"timeout after {timeout}s: {exc}"


def _time_step(
    name: str,
    cmd: list[str],
    *,
    runs: int,
    timeout: int,
) -> StepStats:
    samples: list[float] = []
    ok = 0
    print(f"\n[{name}] {' '.join(cmd)}")
    for i in range(runs):
        elapsed, rc, detail = _run_timed(cmd, timeout=timeout)
        samples.append(elapsed)
        status = "ok" if rc == 0 else f"rc={rc}"
        print(f"  run {i + 1}/{runs}: {elapsed:.3f}s {status}")
        if rc == 0:
            ok += 1
        elif detail:
            print(f"    detail: {detail[:200]}")
    return _stats(name, samples, ok)


def _host_meta() -> dict[str, str]:
    uname = platform.uname()
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "system": uname.system,
        "machine": uname.machine,
        "processor": uname.processor or "",
        "node": uname.node,
    }


def _markdown_table(steps: list[StepStats], *, mode: str, fixture: str, meta: dict[str, str]) -> str:
    lines = [
        f"| step | mode | runs | ok | p50 (s) | p95 (s) | mean (s) | min (s) | max (s) | machine |",
        f"| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    machine = f"{meta.get('system', '?')}/{meta.get('machine', '?')}"
    for s in steps:
        lines.append(
            "| {step} | {mode} | {runs} | {ok} | {p50} | {p95} | {mean} | {min_s} | {max_s} | {machine} |".format(
                step=s.step,
                mode=mode,
                runs=s.runs,
                ok=s.ok_runs,
                p50=s.p50_s if s.p50_s is not None else "—",
                p95=s.p95_s if s.p95_s is not None else "—",
                mean=s.mean_s if s.mean_s is not None else "—",
                min_s=s.min_s if s.min_s is not None else "—",
                max_s=s.max_s if s.max_s is not None else "—",
                machine=machine,
            )
        )
    lines.append("")
    lines.append(f"Fixture: `{fixture}`")
    lines.append(f"Recorded: `{meta.get('timestamp_utc', '')}`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Time Kinocut golden-path baseline steps (WP-F scaffolding)."
    )
    parser.add_argument(
        "--mode",
        choices=("cheap", "full"),
        default="cheap",
        help="cheap=doctor+info (default); full=also time scripts/golden_path.py once per run",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"samples per step (default {DEFAULT_RUNS})",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="video path for info step (default tests/fixtures/golden/workflow_final.mp4)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON summary to stdout after the table",
    )
    parser.add_argument(
        "--markdown-only",
        action="store_true",
        help="print only the markdown results table (for pasting into status doc)",
    )
    args = parser.parse_args(argv)

    if args.runs < 1:
        print("FAIL: --runs must be >= 1", file=sys.stderr)
        return 2

    py = sys.executable
    fixture = args.fixture if args.fixture.is_absolute() else (ROOT / args.fixture)
    if not fixture.is_file():
        print(f"FAIL: fixture not found: {fixture}", file=sys.stderr)
        return 2

    steps: list[StepStats] = []
    steps.append(
        _time_step(
            "doctor",
            [py, "-m", "kinocut", "doctor", "--json"],
            runs=args.runs,
            timeout=STEP_TIMEOUT_S,
        )
    )
    steps.append(
        _time_step(
            "info",
            [py, "-m", "kinocut", "--format", "json", "info", str(fixture)],
            runs=args.runs,
            timeout=STEP_TIMEOUT_S,
        )
    )

    if args.mode == "full":
        gp = ROOT / "scripts" / "golden_path.py"
        if not gp.is_file():
            print(f"FAIL: missing {gp}", file=sys.stderr)
            return 2
        steps.append(
            _time_step(
                "golden_path",
                [py, str(gp)],
                runs=args.runs,
                timeout=FULL_TIMEOUT_S,
            )
        )

    meta = _host_meta()
    table = _markdown_table(steps, mode=args.mode, fixture=str(fixture.relative_to(ROOT)), meta=meta)

    if not args.markdown_only:
        print("\n" + "=" * 60)
        print("Kinocut golden-path timings (WP-F baseline)")
        print(f"mode={args.mode} runs={args.runs}")
        print("=" * 60)
    print(table)

    payload = {
        "schema": "kinocut.golden_path_timings.v1",
        "mode": args.mode,
        "runs": args.runs,
        "fixture": str(fixture.relative_to(ROOT)),
        "host": meta,
        "steps": [asdict(s) for s in steps],
        "claim_note": (
            "Baseline scaffolding only. Not an optimization claim. "
            "Do not bump docs/public_claims.json from this script."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2))

    failed = [s for s in steps if s.ok_runs < s.runs]
    if failed:
        names = ", ".join(s.step for s in failed)
        print(f"\nWARN: incomplete success on: {names}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
