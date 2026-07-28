#!/usr/bin/env python3
"""Read-only operator summary for Kinocut's remaining human gates."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPO = "KyaniteLabs/kinocut"
EXPECTED_POST_RELEASE = tuple(
    sorted(
        {
            *range(63, 83),
            84,
            85,
            86,
            87,
            *range(89, 108),
        }
    )
)


class PendingAuditError(Exception):
    """A bounded local status command could not be completed."""


@dataclass(frozen=True)
class Gate:
    name: str
    state: str
    issues: tuple[int, ...]
    why: str
    next_action: str


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise PendingAuditError(f"timed out: {args[0]}") from error


def _git_state() -> dict[str, Any]:
    remote = _run("git", "remote", "get-url", "origin")
    sync = _run("git", "rev-list", "--left-right", "--count", "master...origin/master")
    return {
        "origin": remote.stdout.strip() if remote.returncode == 0 else "unknown",
        "master_sync": sync.stdout.strip() if sync.returncode == 0 else "unknown",
    }


def _docker_state() -> str:
    if shutil.which("docker") is None:
        return "unavailable"
    result = _run("docker", "info", "--format", "{{.ServerVersion}}")
    return f"ready ({result.stdout.strip()})" if result.returncode == 0 else "installed; daemon unavailable"


def _fetch_issues() -> dict[int, dict[str, Any]] | None:
    if shutil.which("fj") is None:
        return None
    records: list[dict[str, Any]] = []
    for page in (1, 2):
        result = _run(
            "fj",
            "api",
            "GET",
            f"repos/{REPO}/issues?state=open&type=issues&limit=50&page={page}",
        )
        if result.returncode != 0:
            return None
        try:
            records.extend(json.loads(result.stdout))
        except json.JSONDecodeError:
            return None
    return {
        int(record["number"]): record
        for record in records
        if "number" in record and record.get("pull_request") is None
    }


def _labels(issue: dict[str, Any] | None) -> set[str]:
    return {str(label["name"]) for label in (issue or {}).get("labels", []) if "name" in label}


def _post_release_gate(issues: dict[int, dict[str, Any]] | None) -> Gate:
    if issues is None:
        numbers = EXPECTED_POST_RELEASE
        state = "UNKNOWN"
        why = "Forgejo status could not be read."
    else:
        numbers = tuple(
            sorted(
                number
                for number, issue in issues.items()
                if "blocked:post-release" in _labels(issue)
            )
        )
        state = "BLOCKED" if numbers else "REVIEW"
        why = f"{len(numbers)} open issues retain blocked:post-release." if numbers else "No live post-release labels found."
    return Gate(
        name="Post-release backlog",
        state=state,
        issues=numbers,
        why=why,
        next_action="Confirm the real post-release milestone, then explicitly authorize label removal.",
    )


def _build_gates(issues: dict[int, dict[str, Any]] | None, docker: str) -> list[Gate]:
    gates = [
        Gate(
            name="Runner activation",
            state="NEEDS YOU",
            issues=(110,),
            why=f"Docker is {docker}; Forgejo runner registration needs admin access.",
            next_action="Provide runner-admin access and a working Docker daemon.",
        ),
        Gate(
            name="Native MCPB",
            state="NEEDS YOU",
            issues=(125, 257),
            why="Runtime licenses, clean-machine matrices, signing, and release review are external gates.",
            next_action="Approve the runtime/source family and provide macOS, Linux, and Windows runners.",
        ),
    ]
    gates.extend(
        (
            _post_release_gate(issues),
            Gate(
                name="Compositor queue",
                state="QUEUED",
                issues=(34, 35, 36),
                why="These are unblocked, but campaign order places compositor work after Waves D and E.",
                next_action="No decision needed now; the campaign will reach these in order.",
            ),
            Gate(
                name="Directory submission",
                state="NOT AUTHORIZED",
                issues=(88,),
                why="Directory submission requires separate human release authority.",
                next_action="Name the exact directory and explicitly authorize submission when ready.",
            ),
            Gate(
                name="Real-user evidence",
                state="NEEDS REAL USERS",
                issues=(92,),
                why="Listening and first-user evidence cannot be synthesized.",
                next_action="Provide links or notes from actual user conversations when they exist.",
            ),
            Gate(
                name="Dependency dashboard",
                state="AUTOMATIC",
                issues=(3,),
                why="Renovate maintains this tracker automatically.",
                next_action="No action unless a dependency PR needs a product decision.",
            ),
        )
    )
    if issues is not None:
        categorized = {number for gate in gates for number in gate.issues}
        uncategorized = tuple(sorted(set(issues) - categorized))
        if uncategorized:
            gates.append(
                Gate(
                    name="New or uncategorized issues",
                    state="REVIEW",
                    issues=uncategorized,
                    why="These live issues are not yet mapped into the campaign operator view.",
                    next_action="Ask the campaign to classify them before implementation.",
                )
            )
    return gates


def _copy_paste_block() -> str:
    return """Kinocut authority update:
- Post-release milestone is genuinely satisfied: YES / NO
- Remove blocked:post-release labels now: YES / NO
- Runner-admin access and working Docker are available: YES / NO
- Approved MCPB runtime/source family: <name or NOT YET>
- Release actions authorized: NONE / <exact actions>
- Real-user evidence available: NONE / <links or notes>"""


def _format_issues(numbers: tuple[int, ...]) -> str:
    if not numbers:
        return "no issues"
    ranges: list[tuple[int, int]] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))
    return ", ".join(f"#{start}" if start == end else f"#{start}-{end}" for start, end in ranges)


def _render_text(git: dict[str, Any], docker: str, gates: list[Gate], live: bool) -> str:
    lines = [
        "KINOCUT PENDING — HUMAN-FRIENDLY VIEW",
        f"Tracker: {'live Forgejo' if live else 'offline/unknown'}",
        f"Origin: {git['origin']}",
        f"Master sync (local, remote): {git['master_sync']}",
        f"Docker: {docker}",
        "",
    ]
    for index, gate in enumerate(gates, 1):
        issue_text = _format_issues(gate.issues)
        lines.extend(
            (
                f"{index}. [{gate.state}] {gate.name} ({issue_text})",
                f"   Why: {gate.why}",
                f"   You: {gate.next_action}",
            )
        )
    lines.extend(("", "COPY/PASTE THIS BACK WHEN READY", _copy_paste_block()))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--offline", action="store_true", help="skip Forgejo network reads")
    parser.add_argument("--copy-paste", action="store_true", help="print only the authority-update template")
    args = parser.parse_args()
    if args.copy_paste:
        print(_copy_paste_block())
        return 0
    try:
        git = _git_state()
    except PendingAuditError:
        git = {"origin": "unknown", "master_sync": "unknown"}
    try:
        docker = _docker_state()
    except PendingAuditError:
        docker = "status timed out"
    issues = None if args.offline else _fetch_issues()
    gates = _build_gates(issues, docker)
    if args.json:
        print(
            json.dumps(
                {
                    "read_only": True,
                    "tracker_live": issues is not None,
                    "git": git,
                    "docker": docker,
                    "gates": [asdict(gate) for gate in gates],
                    "authority_update_template": _copy_paste_block(),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_render_text(git, docker, gates, issues is not None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
