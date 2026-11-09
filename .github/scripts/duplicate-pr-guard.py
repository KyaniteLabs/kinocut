#!/usr/bin/env python3
"""Flag a pull request whose issue or Linear ticket another PR already covers.

GitHub issues and Linear tickets can track the same work, and an agent
started from one does not see a PR opened against the other. This check
reads the PR's title, body and branch, collects the GitHub issues and
Linear keys it names, and lists any other PR that references the same
thing and is still open or merged within the lookback window. For a GitHub
issue, only PRs that claim it with a closing keyword (Closes/Fixes #N) count,
so follow-ups that merely mention the issue stay quiet.

It only reads PR text through the GitHub API; it never checks out or runs
PR code.

Usage:
  duplicate-pr-guard.py OWNER/REPO PR_NUMBER   Markdown report for an opened PR (empty if clean)
  duplicate-pr-guard.py --ticket "#679 KLH-340" Preflight before starting work; exits 1 if claimed,
                                                2 if it could not check
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys

LINEAR_KEY = re.compile(r"\b(KLH-\d+)\b", re.IGNORECASE)
ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")
LOOKBACK_DAYS = 14

_REFS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        closedByPullRequestsReferences(includeClosedPrs: true, first: 50) {
          nodes { number title state mergedAt url }
        }
      }
    }
  }
}
"""


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def references(text: str) -> tuple[set[int], set[str]]:
    issues = {int(n) for n in ISSUE_REF.findall(text)}
    keys = {k.upper() for k in LINEAR_KEY.findall(text)}
    return issues, keys


def is_live(pr: dict, cutoff: dt.datetime) -> bool:
    state = (pr.get("state") or "").upper()
    if state == "OPEN":
        return True
    merged = pr.get("mergedAt")
    return state == "MERGED" and bool(merged) and dt.datetime.fromisoformat(merged.replace("Z", "+00:00")) >= cutoff


def prs_for_issue(repo: str, number: int) -> list[dict]:
    owner, name = repo.split("/", 1)
    try:
        raw = gh(
            "api", "graphql", "-f", f"query={_REFS_QUERY}",
            "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}",
        )  # fmt: skip
    except subprocess.CalledProcessError as exc:
        if "Could not resolve" in (exc.stderr or ""):
            return []  # no such issue or PR
        raise
    item = json.loads(raw)["data"]["repository"]["issueOrPullRequest"]
    if not item or item["__typename"] != "Issue":
        return []  # a PR reference ("supersedes #12") is not a claim on shared work
    return item["closedByPullRequestsReferences"]["nodes"]


def prs_for_key(repo: str, key: str) -> list[dict]:
    rows = json.loads(
        gh(
            "pr", "list", "--repo", repo, "--state", "all", "--limit", "50",
            "--search", f'"{key}" in:title,body', "--json", "number,title,headRefName,state,mergedAt,url",
        )
    )  # fmt: skip
    # A claim names the key in the title or branch (Linear's own convention); a
    # passing mention in a body does not. Exact match so KLH-34 never hits KLH-340.
    exact = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![0-9])", re.IGNORECASE)
    return [row for row in rows if exact.search(f"{row.get('title') or ''} {row.get('headRefName') or ''}")]


def find_overlaps(repo: str, text: str, exclude: int | None = None) -> dict[int, tuple[dict, set[str]]]:
    issues, keys = references(text)
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=LOOKBACK_DAYS)
    overlaps: dict[int, tuple[dict, set[str]]] = {}
    for issue in sorted(issues):
        for pr in prs_for_issue(repo, issue):
            if pr["number"] != exclude and is_live(pr, cutoff):
                overlaps.setdefault(pr["number"], (pr, set()))[1].add(f"#{issue}")
    for key in sorted(keys):
        for pr in prs_for_key(repo, key):
            if pr["number"] != exclude and is_live(pr, cutoff):
                overlaps.setdefault(pr["number"], (pr, set()))[1].add(key)
    return overlaps


def render(overlaps: dict[int, tuple[dict, set[str]]], headline: str, advice: str) -> str:
    if not overlaps:
        return ""
    lines = [headline, ""]
    for pr_number in sorted(overlaps):
        pr, via = overlaps[pr_number]
        status = "open" if pr["state"].upper() == "OPEN" else f"merged {pr['mergedAt'][:10]}"
        lines.append(f"- #{pr_number} ({status}), via {', '.join(sorted(via))}: {pr['title']}")
    return "\n".join([*lines, "", advice])


def main(repo: str, number: int) -> str:
    """Report for an opened PR (used by the workflow)."""
    me = json.loads(gh("pr", "view", str(number), "--repo", repo, "--json", "title,body,headRefName"))
    text = " ".join([me.get("title") or "", me.get("body") or "", me.get("headRefName") or ""])
    return render(
        find_overlaps(repo, text, exclude=number),
        "**Possible duplicate work.** Another PR already covers what this one references:",
        "Before continuing, compare the two. Close this PR if the other one already covers it, "
        "and port anything it lacks; ignore this if it is a planned follow-up. A Linear key in the "
        "PR body (for example `KLH-123`) lets Linear mark the ticket In Progress so other agents skip it.",
    )


def preflight(repo: str, tickets: str) -> int:
    """Before starting work: exit 1 if the ticket is claimed, 2 if the check could not run."""
    try:
        overlaps = find_overlaps(repo, tickets)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(
            f"UNKNOWN: could not check {tickets} ({type(exc).__name__}). Is `gh` installed and logged in? "
            "Check the issue's linked pull requests on GitHub before starting."
        )
        return 2
    report = render(
        overlaps,
        f"STOP: {tickets} is already claimed by another PR:",
        "Do not start new work. Review that PR, or ask the maintainer what is still missing.",
    )
    print(report or f"OK: no open or recently merged PR claims {tickets}.")
    return 1 if report else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--ticket"]:
        # duplicate-pr-guard.py --ticket "#679 KLH-340" [OWNER/REPO]
        sys.exit(preflight(sys.argv[3] if len(sys.argv) > 3 else "KyaniteLabs/kinocut", sys.argv[2]))
    print(main(sys.argv[1], int(sys.argv[2])))
